const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const load = (name) => {
  const p = path.join(__dirname, "../../web/static", name);
  return fs.existsSync(p) ? require(p) : {};
};
const Fields = load("workspace_fields.js"),
  Design = load("design_workspace.js");
class Element {
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  constructor(tag, doc) {
    this.tagName = tag;
    this.ownerDocument = doc;
    this.children = [];
    this.dataset = {};
    this.value = "";
    this.checked = false;
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
  }
  setAttribute(k, v) {
    this[k] = String(v);
  }
  addEventListener(k, fn) {
    this["on" + k] = fn;
  }
  set innerHTML(_) {
    throw Error("Unsafe HTML");
  }
}
const root = () => {
  const doc = { createElement: (t) => new Element(t, doc) };
  return doc.createElement("div");
};
const all = (el) => [el, ...el.children.flatMap(all)];
const geometry = {
  id: "third_shape",
  version: "1.0.0",
  label: "Third Shape",
  representations: ["solid", "network"],
  default_representation: "solid",
  fields: [{ key: "amount", label: "Amount", type: "number", min: 1, max: 10 }],
  defaults: { amount: 3 },
  representation_parameters: {
    network: {
      fields: [
        { key: "level", label: "Level", type: "number", min: -2, max: 2 },
      ],
      defaults: { level: 0 },
    },
  },
};

test("metadata renders every field kind and preserves hidden values in submission", () => {
  const el = root();
  const fields = [
    { key: "mode", label: "Mode", type: "enum", options: ["a", "b"] },
    {
      key: "size",
      label: "Size",
      type: "number",
      min: 0,
      max: 10,
      unit: "mm",
      visible_when: { field: "mode", equals: "b" },
    },
    { key: "count", label: "Count", type: "integer", min: 1, max: 4 },
    { key: "enabled", label: "Enabled", type: "boolean" },
    { key: "name", label: "Name", type: "text" },
    {
      key: "vector",
      label: "Vector",
      type: "vector",
      length: 3,
      min: 0,
      max: 9,
    },
  ];
  const view = Fields.render(el, fields, {
    mode: "a",
    size: 2,
    count: 1,
    enabled: true,
    name: "<script>",
    vector: [1, 2, 3],
  });
  assert.equal(view.rows.size.hidden, true);
  assert.equal(view.read().size, 2);
  const mode = all(el).find((n) => n.name === "mode");
  mode.value = "b";
  mode.onchange();
  assert.equal(view.rows.size.hidden, false);
  assert.deepEqual(view.read(), {
    mode: "b",
    size: 2,
    count: 1,
    enabled: true,
    name: "<script>",
    vector: [1, 2, 3],
  });
  assert.equal(all(el).find((n) => n.name === "count").step, "1");
  all(el).find((n) => n.name === "size").value = "";
  assert.equal(view.read().size, null);
});
test("representation schemas replace inactive fields without geometry-name branches", () => {
  assert.deepEqual(
    Design.parameters(geometry, "network"),
    geometry.representation_parameters.network,
  );
  assert.deepEqual(Design.parameters(geometry, "solid").defaults, {
    amount: 3,
  });
  assert.deepEqual(
    Design.orientationAxes(
      {
        ...geometry,
        orientation_axes: ["z"],
        representation_orientation_axes: { network: ["x", "y", "z"] },
      },
      "network",
    ),
    ["x", "y", "z"],
  );
});
test("stochastic geometry selection supplies a repeatable seed and refresh preserves user seed", async () => {
  const model = Design.createModel();
  const geometries = [geometry, ...["spinodoid", "voronoi"].map(id => ({...geometry, id, stochastic: true}))];
  await model.selectModule("third", async () => ({geometries}));
  assert.equal(model.draft.seed, null);
  for (const id of ["spinodoid", "voronoi"]) {
    model.selectGeometry(id);
    assert.ok(Number.isInteger(model.draft.seed), `${id} must submit an integer seed`);
    assert.ok(model.draft.seed >= 0 && model.draft.seed <= 4294967295);
    const seed = model.draft.seed;
    model.selectGeometry(id);
    assert.equal(model.draft.seed, seed);
    model.draft.seed = 0;
    await model.selectModule("third", async () => ({geometries}));
    assert.equal(model.draft.seed, 0);
  }
});
test("catalog-driven selection accepts a third provider and rejects stale geometry responses", async () => {
  const model = Design.createModel();
  let release;
  const first = model.selectModule(
    "first",
    () => new Promise((r) => (release = r)),
  );
  await model.selectModule("third", async () => ({ geometries: [geometry] }));
  release({ geometries: [{ ...geometry, id: "old" }] });
  await first;
  assert.equal(model.moduleId, "third");
  assert.equal(model.geometry.id, "third_shape");
  assert.equal(model.draft.parameters.amount, 3);
});
test("same selection refresh and arriving job results cannot replace dirty inputs or relabel old result", async () => {
  const model = Design.createModel();
  await model.selectModule("third", async () => ({ geometries: [geometry] }));
  model.draft.parameters.amount = 7;
  await model.selectModule("third", async () => ({ geometries: [geometry] }));
  assert.equal(model.draft.parameters.amount, 7);
  const job = {
    id: "old",
    state: "succeeded",
    request: {
      module_id: "third",
      geometry_id: "third_shape",
      quality: "preview",
    },
    receipt: {},
  };
  model.acceptJobs([job]);
  await model.selectModule("new", async () => ({
    geometries: [{ ...geometry, id: "next" }],
  }));
  assert.equal(model.jobs[0].request.geometry_id, "third_shape");
  assert.equal(job.request.geometry_id, "third_shape");
});
test("job history bounds rendering and ignores older poll responses", () => {
  const model = Design.createModel();
  const old = model.beginJobs(),
    fresh = model.beginJobs();
  model.acceptJobs(
    Array.from({ length: 30 }, (_, i) => ({
      id: String(i),
      state: "succeeded",
    })),
    fresh,
  );
  model.acceptJobs([{ id: "stale" }], old);
  assert.equal(model.jobs.length, 20);
  assert.equal(model.jobs[0].id, "0");
});
test("API error shapes stay visible and structured numeric validation is not flattened away", () => {
  assert.equal(
    Design.errorMessage({
      detail: {
        code: "invalid_request",
        message: "resolution must be an integer",
      },
    }),
    "resolution must be an integer",
  );
  assert.match(
    Design.errorMessage({
      detail: [{ loc: ["body", "resolution"], msg: "Invalid number" }],
    }),
    /resolution.*Invalid number/,
  );
});
test("concurrent poll and view share one artifact fetch without keeping old large buffers", async () => {
  let requests = 0,
    release;
  const loader = Design.createArtifactLoader(() => {
    requests++;
    return new Promise((r) => (release = r));
  });
  const first = loader("immutable-job-hash"),
    second = loader("immutable-job-hash");
  assert.equal(requests, 1);
  release("bytes");
  assert.equal(await first, "bytes");
  assert.equal(await second, "bytes");
});

test("representation drafts retain independent parameters and valid orientation by provider identity", async () => {
  const model = Design.createModel();
  const descriptor = {
    ...geometry,
    representation_orientation_axes: { solid: ["z"], network: ["x", "y", "z"] },
  };
  await model.selectModule("first", async () => ({ geometries: [descriptor] }));
  model.draft.parameters.amount = 7;
  model.draft.orientation_deg = [0, 0, 25];
  model.selectRepresentation("network");
  assert.deepEqual(model.draft.parameters, { level: 0 });
  assert.deepEqual(model.draft.orientation_deg, [0, 0, 0]);
  model.draft.parameters.level = 0.25;
  model.draft.orientation_deg = [15, 10, 30];
  model.selectRepresentation("solid");
  assert.deepEqual(model.draft.parameters, { amount: 7 });
  assert.deepEqual(model.draft.orientation_deg, [0, 0, 25]);
  model.selectRepresentation("network");
  assert.deepEqual(model.draft.parameters, { level: 0.25 });
  assert.deepEqual(model.draft.orientation_deg, [15, 10, 30]);
  await model.selectModule("second", async () => ({
    geometries: [descriptor],
  }));
  assert.equal(model.draft.parameters.amount, 3);
  await model.selectModule("first", async () => ({ geometries: [descriptor] }));
  assert.equal(model.draft.parameters.amount, 7);
  await model.selectModule("first", async () => ({
    geometries: [{ ...descriptor, version: "2.0.0" }],
  }));
  assert.equal(model.draft.parameters.amount, 3);
});

// Real boot handlers, delayed transport only. The request assertion catches
// invisible stale-model commits even when the visible field remains unchanged.
async function bootHarness(actions = ["preview", "generate"]) {
  const nodes = new Map();
  const doc = { createElement: (t) => new Element(t, doc),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div", doc));
      return nodes.get(id);
    }};
  const g = (id) => ({...geometry, id: "g" + id,
    agent_handoff: id === "a", fields: [{key: id + "_value", label: id, type: "number"}],
    defaults: {[id + "_value"]: 1}});
  const profiles = ["a", "b", "missing"].map((id) => ({id, name: id, revision: 1,
    available: id !== "missing", request: {module_id: id, geometry_id: "g" + id,
      provider_version: "1.0.0", representation: "solid", parameters: {[id + "_value"]: 1},
      specimen_size_mm: [10,10,10], orientation_deg: [0,0,0], seed: null, quality:"preview", resolution:48}}));
  let release, delayed, deletion;
  const sent = [];
  global.document = doc;
  global.window = {addEventListener() {}};
  global.WorkspaceFields = Fields;
  global.confirm = () => true;
  const timeout = global.setTimeout;
  global.setTimeout = () => 0;
  global.fetch = async (url, options) => {
    if (options.method !== "GET") sent.push({url, method: options.method, body: JSON.parse(options.body)});
    if (url.endsWith("/geometries") && url.includes("/" + delayed + "/"))
      await new Promise((resolve) => {release = resolve;});
    if (options.method === "DELETE" && deletion)
      await new Promise((resolve) => {release = resolve;});
    let data;
    if (url.endsWith("/modules")) data = {modules: ["a","b"].map((id) => ({id, label:id,
      actions, state:{enabled:true}, icon_url:"/icon"})), errors:[]};
    else if (url.endsWith("/geometries")) data = {geometries:[g(url.split("/").at(-2))]};
    else if (url.endsWith("/jobs")) data = {jobs:[]};
    else if (options.method === "POST" || options.method === "PUT") data = {id:"saved", ...JSON.parse(options.body)};
    else data = {profiles};
    return {ok:true, json:async () => data};
  };
  Design.boot();
  const flush = async () => {for (let i=0;i<20;i++) await Promise.resolve();};
  await flush();
  const node = (id) => doc.getElementById(id);
  node("preview-resolution").value = "48";
  node("final-resolution").value = "96";
  const choose = (id) => {node("profile-select").value=id; return node("profile-select").onchange();};
  return {node, sent, choose, flush, delay: (id) => delayed=id, deleteDelay: () => deletion=true,
    release: () => release(), close: () => {global.setTimeout=timeout;}};
}

for (const interruption of ["new", "empty", "unavailable"]) {
  test("profile load interrupted by " + interruption + " cannot commit invisible request", async () => {
    const h = await bootHarness();
    try {
      await h.choose("b"); h.delay("a"); const loading = h.choose("a"); await h.flush();
      if (interruption === "new") h.node("new-profile").onclick();
      else await h.choose(interruption === "empty" ? "" : "missing");
      h.release(); await loading;
      assert.equal(h.node("geometry-select").value, "gb");
      if (interruption === "unavailable") h.node("new-profile").onclick();
      h.node("profile-name").value="new draft";
      await h.node("save-profile").onclick();
      const outgoing = h.sent.at(-1).body.request;
      assert.equal(outgoing.module_id, "b");
      assert.equal(outgoing.geometry_id, "gb");
      assert.deepEqual(outgoing.parameters, {b_value:1});
    } finally {h.close();}
  });
}

test("delayed delete cannot clear another selected profile or change next update target", async () => {
  const h = await bootHarness();
  try {
    await h.choose("a"); h.deleteDelay();
    const deleting=h.node("delete-profile").onclick(); await h.flush();
    await h.choose("b"); h.release(); await deleting;
    assert.equal(h.node("profile-name").value, "b");
    await h.node("save-profile").onclick();
    assert.equal(h.sent.at(-1).url, "/api/design/profiles/b");
    assert.equal(h.sent.at(-1).method, "PUT");
    assert.equal(h.sent.at(-1).body.request.geometry_id, "gb");
  } finally {h.close();}
});

test("preview-only module controls and manual-only provider disclosure follow metadata", async () => {
  const h=await bootHarness(["preview"]);
  try {
    await h.choose("b");
    assert.equal(h.node("preview-design").disabled, false);
    assert.equal(h.node("generate-design").disabled, true);
    assert.match(h.node("selection-state").textContent, /Manual only/);
    await h.node("generate-design").onclick(); // scripted calls must also fail closed
    assert.equal(h.sent.filter((r) => r.url.endsWith("/jobs")).length, 0);
    await h.choose("a");
    assert.match(h.node("selection-state").textContent, /Manual only.*preview and generate/);
  } finally {h.close();}
});

for (const actions of [["generate"], ["preview", "generate"]]) {
  test("new profile POST uses supported quality for " + actions.join("+"), async () => {
    const h = await bootHarness(actions);
    try {
      // Select a module, not a saved profile: this draft has no quality yet.
      await h.node("design-modules").children[0].children[0].onclick();
      h.node("profile-name").value = "New supported draft";
      await h.node("save-profile").onclick();
      assert.equal(h.sent.at(-1).url, "/api/design/profiles");
      assert.equal(h.sent.at(-1).method, "POST");
      assert.equal(h.sent.at(-1).body.request.quality, actions.length === 1 ? "final" : "preview");
      assert.equal(h.sent.at(-1).body.request.resolution, actions.length === 1 ? 96 : 48);
      assert.equal(h.node("generate-design").disabled, false);
      assert.equal(h.node("preview-design").disabled, actions.length === 1);
      assert.match(h.node("selection-state").textContent, actions.length === 1
        ? /Manual only.*preview and generate/ : /Agent handoff supported/);
    } finally {h.close();}
  });
}
