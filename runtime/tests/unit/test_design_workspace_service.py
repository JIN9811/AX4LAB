"""Durable public behavior; doubles replace only expensive numerical workers."""
from concurrent.futures import Future
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest

from workspaces.design.catalog import DesignCatalog
from workspaces.design.service import DesignService, DesignError

MODULE = 'metamaterial_unit_cell_designer'


def request(**overrides):
    return dict(module_id=MODULE, geometry_id='simple_cubic', provider_version='1.0.0', **overrides)


class Worker:
    def __init__(self):
        self.calls = []
        self.ready = threading.Event()

    def submit(self, job, payload, *, timeout, cancellation):
        assert job == 'geometry.design_generate'
        future = Future()
        self.calls.append((deepcopy(payload), future, cancellation))
        self.ready.set()
        return future, cancellation

    def finish(self, index=0, *, corrupt=False):
        payload, future, _ = self.calls[index]
        root = Path(payload['output_dir'])
        root.mkdir(parents=True)
        data = b'controlled numerical artifact'
        (root / 'geometry.stl').write_bytes(data)
        receipt = dict(schema='ax4lab.geometry_receipt.v1', ok=True,
            request=payload['request'], request_sha256=hashlib.sha256(json.dumps(payload['request'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
            source_fingerprint=payload['source_fingerprint'], identity=payload['identity'],
            artifacts={'stl':dict(basename='geometry.stl', sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))})
        (root / 'receipt.json').write_text(json.dumps(receipt))
        if corrupt:
            (root / 'geometry.stl').write_bytes(b'tampered')
        future.set_result(receipt)


def terminal(service, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.job(job_id)
        if result['state'] in {'succeeded', 'failed', 'cancelled', 'interrupted'}:
            return result
        time.sleep(.01)
    pytest.fail('Job did not settle')


@pytest.fixture
def service(tmp_path):
    worker = Worker()
    service = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=worker)
    yield service, worker
    service.shutdown()


def test_job_order_is_newest_first_after_reload_and_retry_does_not_reorder(tmp_path):
    worker = Worker()
    service = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=worker)
    try:
        first = service.submit(request(), idempotency_key='first-order')
        assert worker.ready.wait(2)
        second = service.submit(request(resolution=64), idempotency_key='second-order')
        assert [job['id'] for job in service.jobs()] == [second['id'], first['id']]
        assert first['created_sequence'] < second['created_sequence']
        assert service.submit(request(), idempotency_key='first-order')['created_sequence'] == first['created_sequence']
    finally:
        service.shutdown()
    reloaded = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=Worker())
    try:
        assert [job['id'] for job in reloaded.jobs()] == [second['id'], first['id']]
        assert reloaded.submit(request(), idempotency_key='first-order')['created_sequence'] == first['created_sequence']
        # Legacy records remain visible, deterministically ordered behind sequenced records.
        data = deepcopy(reloaded.store.data)
        data['jobs'][first['id']].pop('created_sequence')
        reloaded.store.save(data)
        third = reloaded.submit(request(resolution=80), idempotency_key='third-order')
        assert third['created_sequence'] > second['created_sequence']
        assert [job['id'] for job in reloaded.jobs()] == [third['id'], second['id'], first['id']]
    finally:
        reloaded.shutdown()


def test_profiles_revision_confirmation_and_restart(service, tmp_path):
    s, _ = service
    profile = s.create_profile({'name':'First', 'request':request()})
    assert profile['revision'] == 1
    with pytest.raises(DesignError, match='revision'):
        s.update_profile(profile['id'], {'name':'Wrong', 'request':request()}, 2)
    updated = s.update_profile(profile['id'], {'name':'Second', 'request':request()}, 1)
    assert updated['revision'] == 2
    with pytest.raises(DesignError, match='confirm'):
        s.delete_profile(profile['id'], 2, confirmed=False)
    other = DesignService(tmp_path/'memory', tmp_path/'other', executor=Worker())
    assert other.profile(profile['id'])['name'] == 'Second'
    other.shutdown()
    s.delete_profile(profile['id'], 2, confirmed=True)
    assert s.profiles() == []


def test_failed_atomic_write_leaves_profile_unchanged(service, monkeypatch):
    s, _ = service
    p = s.create_profile({'name':'Before', 'request':request()})
    monkeypatch.setattr('workspaces.design.profiles.os.replace', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(DesignError):
        s.update_profile(p['id'], {'name':'After', 'request':request()}, 1)
    assert s.profile(p['id'])['name'] == 'Before'


def test_removed_provider_profile_and_module_state(service, tmp_path):
    s, _ = service
    p = s.create_profile({'name':'Saved', 'request':request()})
    state = s.module_state(MODULE, enabled=False, revision=1)
    assert state == {'enabled':False, 'revision':2}
    with pytest.raises(DesignError, match='disabled'):
        s.submit(request(), idempotency_key='disabled')
    with pytest.raises(DesignError, match='revision'):
        s.module_state(MODULE, enabled=True, revision=1)
    s.catalog = DesignCatalog(tmp_path/'empty')
    assert s.profile(p['id'])['available'] is False
    with pytest.raises(DesignError):
        s.validate(request())


def test_idempotency_queue_pin_refresh_and_no_resubmission(service):
    s, w = service
    original = request()
    a = s.submit(original, idempotency_key='a')
    assert w.ready.wait(2)
    original['geometry_id'] = 'missing'
    assert s.submit(request(), idempotency_key='a')['id'] == a['id']
    with pytest.raises(DesignError, match='idempotency'):
        s.submit(request(resolution=64), idempotency_key='a')
    b = s.submit(request(), idempotency_key='b')
    with pytest.raises(DesignError, match='queue'):
        s.submit(request(), idempotency_key='c')
    s.refresh()
    assert w.calls[0][0]['request']['geometry_id'] == 'simple_cubic'
    assert w.calls[0][0]['source_fingerprint'] == a['source_fingerprint']
    assert s.job(a['id'])['id'] == a['id']
    s.cancel(b['id'])
    w.finish()
    assert terminal(s, a['id'])['state'] == 'succeeded'
    assert len(w.calls) == 1


def test_cancel_wins_late_completion_and_hides_artifacts(service):
    s, w = service
    job = s.submit(request(), idempotency_key='cancel')
    assert w.ready.wait(2)
    assert s.cancel(job['id'])['state'] == 'cancelled'
    assert w.calls[0][2].is_set()
    w.finish()
    assert terminal(s, job['id'])['state'] == 'cancelled'
    with pytest.raises(DesignError):
        s.artifact(job['id'], 'stl')


def test_hash_mismatch_never_publishes_receipt(service):
    s, w = service
    j = s.submit(request(), idempotency_key='bad')
    assert w.ready.wait(2)
    w.finish(corrupt=True)
    result = terminal(s, j['id'])
    assert result['state'] == 'failed'
    assert 'receipt' not in result


def test_restart_marks_unfinished_interrupted_without_resubmit(service, tmp_path):
    s, w = service
    j = s.submit(request(), idempotency_key='restart')
    assert w.ready.wait(2)
    other_worker = Worker()
    other = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=other_worker)
    assert other.job(j['id'])['state'] == 'interrupted'
    assert other.submit(request(), idempotency_key='restart')['state'] == 'interrupted'
    assert other_worker.calls == []
    other.shutdown()


def test_unconfigured_pool_fails_explicitly_not_inline(tmp_path):
    s = DesignService(tmp_path/'memory', tmp_path/'artifacts')
    try:
        with pytest.raises(DesignError, match='not configured'):
            s.submit(request(), idempotency_key='no-pool')
        assert s.jobs() == []
    finally:
        s.shutdown()


def test_receipt_write_failure_does_not_publish_success(service, monkeypatch):
    s, w = service
    j = s.submit(request(), idempotency_key='write-failure')
    assert w.ready.wait(2)
    monkeypatch.setattr('workspaces.design.profiles.os.replace', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    w.finish()
    result = terminal(s, j['id'])
    assert result['state'] == 'failed'
    assert 'receipt' not in result
    assert not (Path(w.calls[0][0]['output_dir'])/'receipt.json').exists()


def test_finished_job_cancel_is_noop_and_download_detects_tampering(service):
    s, w = service
    j = s.submit(request(), idempotency_key='complete')
    assert w.ready.wait(2)
    w.finish()
    assert terminal(s, j['id'])['state'] == 'succeeded'
    assert s.cancel(j['id'])['state'] == 'succeeded'
    file = s.artifact(j['id'], 'stl')
    file.write_bytes(b'changed')
    with pytest.raises(DesignError, match='hash'):
        s.artifact(j['id'], 'stl')


def test_missing_receipt_is_explicit_artifact_error(service):
    s, w = service
    job = s.submit(request(), idempotency_key='missing-receipt')
    assert w.ready.wait(2)
    w.finish()
    assert terminal(s, job['id'])['state'] == 'succeeded'
    (Path(w.calls[0][0]['output_dir'])/'receipt.json').unlink()
    with pytest.raises(DesignError, match='Artifact'):
        s.artifact(job['id'], 'stl')


def test_worker_error_does_not_leak_private_host_paths(service):
    s, w = service
    job = s.submit(request(), idempotency_key='private-error')
    assert w.ready.wait(2)
    w.calls[0][1].set_exception(OSError(f"Cannot write {w.calls[0][0]['output_dir']}/geometry.stl"))
    result = terminal(s, job['id'])
    assert result['state'] == 'failed'
    assert str(s.artifact_root) not in result['error']['message']


def test_completed_worker_timeout_is_terminal_not_an_endless_wait(service):
    s, w = service
    job = s.submit(request(), idempotency_key='deadline')
    assert w.ready.wait(2)
    w.calls[0][1].set_exception(TimeoutError('CPU job exceeded its compute deadline'))
    assert terminal(s, job['id'])['state'] == 'failed'


def test_success_between_poll_timeout_and_done_preserves_receipt(tmp_path):
    class CompletingWorker(Worker):
        def submit(self, *args, **kwargs):
            future, cancellation = super().submit(*args, **kwargs)
            worker = self

            class CompletingFuture:
                def result(self, timeout=None):
                    if not future.done():
                        # Simulate a pending poll timing out, without timing/sleeps.
                        raise TimeoutError('poll expired')
                    return future.result(timeout=timeout)

                def done(self):
                    # Worker succeeds in the gap after the timed-out poll.
                    if not future.done():
                        worker.finish()
                    return future.done()

            return CompletingFuture(), cancellation

    worker = CompletingWorker()
    service = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=worker)
    try:
        job = service.submit(request(), idempotency_key='poll-completion-race')
        result = terminal(service, job['id'])
        assert result['state'] == 'succeeded', result
        assert result['receipt']['request']['geometry_id'] == 'simple_cubic'
        assert service.artifact(job['id'], 'stl').read_bytes() == b'controlled numerical artifact'
        assert (Path(worker.calls[0][0]['output_dir'])/'receipt.json').is_file()
    finally:
        service.shutdown()


def test_disable_does_not_cancel_accepted_job_and_state_is_durable(service, tmp_path):
    s, w = service
    j = s.submit(request(), idempotency_key='accepted')
    assert w.ready.wait(2)
    s.module_state(MODULE, enabled=False, revision=1)
    w.finish()
    assert terminal(s, j['id'])['state'] == 'succeeded'
    other = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=Worker())
    assert other.module_state(MODULE)['enabled'] is False
    assert other.job(j['id'])['receipt']['request']['geometry_id'] == 'simple_cubic'
    other.shutdown()


def test_concurrent_submissions_are_bounded_and_unique(service):
    from concurrent.futures import ThreadPoolExecutor
    s, _ = service
    def attempt(i):
        try:
            return s.submit(request(), idempotency_key=f'parallel-{i}')['id']
        except DesignError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(attempt, range(12)))
    assert values.count('queue_full') == 10
    assert len(set(values) - {'queue_full'}) == 2


def test_unknown_provider_not_substituted_and_symlink_artifact_rejected(service, tmp_path):
    s, w = service
    bad = request()
    bad['geometry_id'] = 'missing'
    with pytest.raises(DesignError):
        s.submit(bad, idempotency_key='unknown')
    j = s.submit(request(), idempotency_key='symlink')
    assert w.ready.wait(2)
    w.finish()
    assert terminal(s, j['id'])['state'] == 'succeeded'
    file = s.artifact(j['id'], 'stl')
    outside = tmp_path/'outside.stl'
    outside.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(outside)
    with pytest.raises(DesignError, match='containment'):
        s.artifact(j['id'], 'stl')
