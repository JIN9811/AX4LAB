import pytest


def parser(module, variant=None):
    from device_bridges.serial_communication.catalog import ModuleCatalog
    return ModuleCatalog().protocol(module, variant)


def test_cas_split_date_weight_negative_and_no_unjustified_stability():
    p = parser('cas_mwii_plus')
    assert p.request() == b'P'
    assert p.feed(b'\r\n2026/11/02\r\n 14:55:57 W:    8.') == []
    rows = p.feed(b'56 g  \r\n 14:55:58 W:-   0.02 g  \r\n')
    assert [r['values']['weight'] for r in rows] == [8.56, -0.02]
    assert rows[0]['device_date'] == '2026/11/02'
    assert rows[0]['units']['weight'] == 'g'
    assert rows[0]['stable'] is None
    assert p.feed(b'garbage\r\n') == []


def qm_frame(variant):
    # Independent hand-constructed values: force 123.45, DISP1 -0.50, DISP2 549.99.
    fields = b'+001234521-000005020+005499920'
    if variant == 'observed60':
        body = b'000' + fields + b'+000000020' + b'000101001210'
    else:
        body = b'LD00000' + fields + (b'+000000020' if variant == 'encoder_pot52' else b'')
    return b'\x02' + body + f'{sum(body) % 256:03d}'.encode() + b'\x03'


@pytest.mark.parametrize('variant,length', [('encoder42',42),('encoder_pot52',52),('observed60',60)])
def test_qm_split_frame_and_checksum(variant, length):
    p = parser('qm_indicator', variant)
    f = qm_frame(variant)
    assert len(f) == length
    assert p.feed(b'noise'+f[:17]) == []
    rows = p.feed(f[17:])
    assert len(rows) == 1
    assert rows[0]['values']['load'] == 123.45
    assert rows[0]['values']['disp1'] == -0.50
    assert rows[0]['values']['disp2'] == 549.99
    assert rows[0]['checksum_valid'] is True
    assert 'absolute_height' not in rows[0]['values']
    assert p.feed(f[:-4]+b'999\x03') == []
    assert p.errors == 1
    assert p.feed(f) and p.request() is None


def test_qm_unknown_layout_does_not_guess():
    p = parser('qm_indicator', 'encoder42')
    assert p.feed(qm_frame('observed60')) == []
    assert p.errors == 1
def test_cas_rejects_nonfinite_values():
    from device_bridges.serial_communication.catalog import ModuleCatalog
    parser=ModuleCatalog().protocol('cas_mwii_plus')
    assert parser.feed(b'12:00:00 W: '+b'9'*400+b' g\r\n')==[]
    assert parser.errors==1


@pytest.mark.parametrize('tail,checksum,code,capacity', [
    (b'000001000010', b'109', 0, 1000),
    (b'000101000010', b'110', 1, 2000),
    (b'000201000010', b'111', 2, 5000),
    (b'000301000010', b'112', 3, 10000),
])
def test_qm_observed_range_change_uses_byte_48_not_fourth_numeric_field(tail, checksum, code, capacity):
    # Actual passive capture while the operator changed Load Range, 2026-11-02.
    frame = b'\x02000+000000010-000002920+005149820+000000020' + tail + checksum + b'\x03'
    p = parser('qm_indicator', 'observed60')
    row, = p.feed(frame)
    assert row['load_range_code'] == code
    assert row['values']['load_range'] == capacity
    assert row['units']['load_range'] == 'kgf'
    assert row['values']['pot'] == 0
    assert row['values']['load'] == 0
    assert row['values']['disp1'] == -0.29
    assert row['values']['disp2'] == 514.98
    assert row['raw_hex'] == frame.hex()
    assert p.request() is None


def test_qm_unknown_range_keeps_measurement_without_guessing_capacity():
    frame = b'\x02000+000000010-000002920+005149820+000000020000901000010118\x03'
    row, = parser('qm_indicator', 'observed60').feed(frame)
    assert row['load_range_code'] == 9
    assert row['values']['load_range'] is None
    assert row['values']['disp2'] == 514.98


@pytest.mark.parametrize('variant', ['encoder42', 'encoder_pot52'])
def test_qm_manual_format_does_not_inherit_site_specific_kgf_table(variant):
    row, = parser('qm_indicator', variant).feed(qm_frame(variant))
    assert row['load_range_code'] == 0
    assert row['values']['load_range'] is None
