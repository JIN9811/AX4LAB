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
