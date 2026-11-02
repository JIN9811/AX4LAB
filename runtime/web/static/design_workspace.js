(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.DesignWorkspace = api;
    document.addEventListener("DOMContentLoaded", api.boot);
  }
})(globalThis, function () {
  "use strict";
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const parameters = (geometry, representation) =>
    geometry.representation_parameters?.[representation] || {
      fields: geometry.fields || [],
      defaults: geometry.defaults || {},
    };
  const orientationAxes = (geometry, representation) =>
    geometry.representation_orientation_axes?.[representation] ||
    geometry.orientation_axes || ["x", "y", "z"];
  function errorMessage(body) {
    const d = body?.detail ?? body;
    return typeof d === "string"
      ? d
      : Array.isArray(d)
        ? d.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("; ")
        : d?.message || "Request failed";
  }
  function createArtifactLoader(fetcher) {
    const pending = new Map();
    return (key) => {
      if (!pending.has(key)) {
        const promise = fetcher(key).finally(() => pending.delete(key));
        pending.set(key, promise);
      }
      return pending.get(key);
    };
  }
  function createModel() {
    let selection = 0,
      poll = 0;
    const representations = new Map();
    const representationKey = (draft, representation = draft.representation) =>
      JSON.stringify([
        draft.module_id,
        draft.provider_version,
        draft.geometry_id,
        representation,
      ]);
    function stateFor(draft, geometry, representation) {
      const key = representationKey(draft, representation);
      if (!representations.has(key)) {
        representations.set(key, {
          parameters: clone(parameters(geometry, representation).defaults),
          orientation_deg: [0, 0, 0],
        });
      }
      return clone(representations.get(key));
    }
    return {
      moduleId: null,
      geometry: null,
      geometries: [],
      draft: null,
      jobs: [],
      invalidateSelection() {
        selection++;
      },
      async selectModule(id, fetcher) {
        const token = ++selection;
        const data = await fetcher(id);
        if (token !== selection) return false;
        const same = this.moduleId === id;
        this.moduleId = id;
        this.geometries = data.geometries;
        const previous =
          same &&
          this.geometries.find(
            (g) =>
              g.id === this.geometry?.id &&
              g.version === this.geometry?.version,
          );
        if (previous) {
          this.geometry = previous;
        } else this.selectGeometry(this.geometries[0]?.id);
        return true;
      },
      rememberRepresentation() {
        if (this.draft)
          representations.set(representationKey(this.draft), {
            parameters: clone(this.draft.parameters),
            orientation_deg: clone(this.draft.orientation_deg),
          });
      },
      selectRepresentation(representation) {
        this.rememberRepresentation();
        Object.assign(
          this.draft,
          stateFor(this.draft, this.geometry, representation),
          { representation },
        );
      },
      selectGeometry(id) {
        this.rememberRepresentation();
        this.geometry = this.geometries.find((g) => g.id === id) || null;
        const g = this.geometry;
        this.draft = g
          ? {
              module_id: this.moduleId,
              geometry_id: g.id,
              provider_version: g.version,
              representation: g.default_representation,
              parameters: clone(
                parameters(g, g.default_representation).defaults,
              ),
              specimen_size_mm: [30, 30, 30],
              orientation_deg: [0, 0, 0],
              seed: null,
            }
          : null;
        if (this.draft)
          Object.assign(
            this.draft,
            stateFor(this.draft, g, g.default_representation),
          );
      },
      beginJobs() {
        return ++poll;
      },
      acceptJobs(jobs, token = poll) {
        if (token !== poll) return false;
        this.jobs = clone(jobs).slice(0, 20);
        return true;
      },
    };
  }
  function boot() {
    const $ = (id) => document.getElementById(id);
    if (!$("design-page")) return;
    const model = createModel();
    let modules = [],
      profiles = [],
      profile = null,
      fields = null,
      common = null,
      desiredJob = null,
      loadedJob = null,
      assetToken = 0,
      catalogToken = 0,
      profileToken = 0,
      profileContext = 0,
      editGeneration = 0,
      fieldGeneration = 0,
      viewer = null,
      noticeJob = null;
    const message = (text, error = false, jobId = null) => {
      noticeJob = jobId;
      const el = $("design-message");
      el.textContent = text;
      el.hidden = !text;
      el.dataset.error = String(error);
    };
    async function api(path, method = "GET", body) {
      const response = await fetch("/api/design" + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      if (!response.ok) throw Error(errorMessage(data));
      return data;
    }
    const action = (fn) => async (event) => {
      try {
        await fn(event);
      } catch (error) {
        message(error.message, true);
      }
    };
    const button = (label, fn) => {
      const el = document.createElement("button");
      el.className = "btn mini";
      el.textContent = label;
      el.type = "button";
      el.onclick = action(fn);
      return el;
    };
    function options(el, items, value) {
      el.replaceChildren();
      for (const [id, label] of items) {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = label;
        el.append(option);
      }
      if (value != null) el.value = value;
    }
    function readDraft() {
      if (!model.draft) throw Error("Select an available geometry");
      if (fields) model.draft.parameters = fields.read();
      if (common) {
        const values = common.read();
        model.draft.specimen_size_mm = values.specimen_size_mm;
        model.draft.orientation_deg = values.orientation_deg;
        model.draft.seed = values.seed;
      }
      return clone(model.draft);
    }
    function dirty() {
      editGeneration++;
      $("save-state").textContent = "Unsaved";
    }
    function changeProfileContext() {
      model.invalidateSelection();
      profileContext++;
      editGeneration = 0;
      $("save-state").textContent = "";
    }
    for (const id of ["profile-name", "preview-resolution", "final-resolution"])
      $(id).addEventListener("input", dirty);
    function renderFields() {
      const generation = ++fieldGeneration;
      const g = model.geometry,
        d = model.draft;
      $("design-editor").hidden = !g;
      if (!g) return;
      options(
        $("geometry-select"),
        model.geometries.map((g) => [g.id, g.label]),
        g.id,
      );
      options(
        $("representation-select"),
        g.representations.map((r) => [r, r.replaceAll("_", " ")]),
        d.representation,
      );
      const schema = parameters(g, d.representation);
      fields = WorkspaceFields.render(
        $("design-fields"),
        schema.fields,
        d.parameters,
        (values) => {
          if (generation !== fieldGeneration) return;
          d.parameters = values;
          dirty();
        },
      );
      common = WorkspaceFields.render(
        $("design-common"),
        [
          {
            key: "specimen_size_mm",
            label: "Specimen size",
            type: "vector",
            length: 3,
            min: 0.001,
            max: 1000,
            unit: "mm",
          },
          {
            key: "orientation_deg",
            label: "Orientation · X / Y / Z",
            type: "vector",
            length: 3,
            min: -360,
            max: 360,
            unit: "deg",
          },
          {
            key: "seed",
            label: "Seed",
            type: "integer",
            min: 0,
            max: 4294967295,
          },
        ],
        d,
        (values) => {
          if (generation !== fieldGeneration) return;
          Object.assign(d, values);
          dirty();
        },
      );
      const axes = orientationAxes(g, d.representation);
      common.controls.orientation_deg.forEach((el, i) => {
        el.disabled = !axes.includes(["x", "y", "z"][i]);
      });
      updateAvailability();
    }
    function updateAvailability() {
      const module = modules.find((m) => m.id === model.moduleId);
      const available =
        module?.state.enabled &&
        Boolean(model.geometry);
      $("save-profile").disabled = !available;
      $("preview-design").disabled = !available || !module.actions?.includes("preview");
      $("generate-design").disabled = !available || !module.actions?.includes("generate");
      const selectedProfile =
        profiles.find((p) => p.id === profile?.id) || profile;
      if (selectedProfile?.available === false)
        $("save-profile").disabled = true;
      $("selection-state").textContent = available
        ? model.geometry.agent_handoff === true
          ? ["preview", "generate"].every((action) => module.actions?.includes(action))
            ? "Agent handoff supported · geometry checks required"
            : "Manual only · agent handoff requires preview and generate"
          : "Manual only · no agent handoff"
        : model.moduleId
          ? "Module unavailable"
          : "";
    }
    async function selectModule(id) {
      readIfPresent();
      changeProfileContext();
      profile = null;
      $("profile-select").value = "";
      $("profile-name").value = "";
      if (
        await model.selectModule(id, (id) =>
          api(`/modules/${encodeURIComponent(id)}/geometries`),
        )
      ) {
        renderFields();
        renderModules();
      }
    }
    function readIfPresent() {
      if (model.draft && fields) readDraft();
    }
    function renderModules() {
      const root = $("design-modules");
      root.replaceChildren();
      for (const module of modules) {
        const card = document.createElement("article");
        card.className = "workspace-card design-module";
        const select = button(module.label, () => selectModule(module.id));
        select.className = "workspace-launch";
        select.disabled = !module.state.enabled;
        select.setAttribute(
          "aria-pressed",
          String(model.moduleId === module.id),
        );
        const image = document.createElement("img");
        image.src = module.icon_url;
        image.alt = "";
        image.width = 72;
        image.height = 72;
        const label = document.createElement("strong");
        label.textContent = module.label;
        select.replaceChildren(image, label);
        const toggle = button(
          module.state.enabled ? "Disable" : "Enable",
          async () => {
            await api(`/modules/${module.id}/state`, "PUT", {
              enabled: !module.state.enabled,
              revision: module.state.revision,
            });
            await refresh();
          },
        );
        toggle.setAttribute(
          "aria-label",
          `${module.state.enabled ? "Disable" : "Enable"} ${module.label}`,
        );
        card.append(select, toggle);
        root.append(card);
      }
      updateAvailability();
    }
    async function refreshProfiles() {
      const token = ++profileToken;
      const data = await api("/profiles");
      if (token !== profileToken) return;
      profiles = data.profiles;
      options(
        $("profile-select"),
        [
          ["", "New profile"],
          ...profiles.map((p) => [
            p.id,
            p.name + (p.available ? "" : " · Unavailable"),
          ]),
        ],
        profile?.id || "",
      );
    }
    async function refresh() {
      const token = ++catalogToken;
      readIfPresent();
      const data = await api("/modules/refresh", "POST");
      if (token !== catalogToken) return;
      modules = data.modules;
      renderModules();
      await refreshProfiles();
      if (data.errors.length)
        message(data.errors.map((e) => e.message).join("; "), true);
      if (model.moduleId && modules.some((m) => m.id === model.moduleId)) {
        if (
          await model.selectModule(model.moduleId, (id) =>
            api(`/modules/${id}/geometries`),
          )
        )
          renderFields();
      }
      updateAvailability();
    }
    $("refresh-modules").onclick = action(refresh);
    $("geometry-select").onchange = () => {
      readIfPresent();
      model.selectGeometry($("geometry-select").value);
      renderFields();
      dirty();
    };
    $("representation-select").onchange = () => {
      readDraft();
      model.selectRepresentation($("representation-select").value);
      renderFields();
      dirty();
    };
    $("profile-select").onchange = action(async () => {
      changeProfileContext();
      const id = $("profile-select").value;
      if (!id) {
        profile = null;
        $("profile-name").value = "";
        updateAvailability();
        return;
      }
      const chosen = profiles.find((p) => p.id === id);
      profile = chosen;
      $("profile-name").value = chosen.name;
      if (!chosen.available) {
        updateAvailability();
        message(chosen.unavailable_reason || "Profile unavailable", true);
        return;
      }
      const context = profileContext;
      if (
        await model.selectModule(chosen.request.module_id, (id) =>
          api(`/modules/${id}/geometries`),
        )
      ) {
        if (context !== profileContext || profile?.id !== id) return;
        model.selectGeometry(chosen.request.geometry_id);
        if (model.geometry?.version !== chosen.request.provider_version)
          throw Error("Profile provider unavailable");
        model.draft = clone(chosen.request);
        if (chosen.request.quality === "final")
          $("final-resolution").value = chosen.request.resolution;
        else $("preview-resolution").value = chosen.request.resolution;
        renderFields();
        renderModules();
        message("");
      }
    });
    $("new-profile").onclick = () => {
      changeProfileContext();
      profileToken++;
      profile = null;
      $("profile-select").value = "";
      $("profile-name").value = "";
      $("save-state").textContent = "";
      updateAvailability();
    };
    $("save-profile").onclick = action(async () => {
      const context = profileContext,
        generation = editGeneration;
      const request = readDraft();
      const module = modules.find((m) => m.id === model.moduleId);
      request.quality = request.quality || (module?.actions?.includes("preview") ? "preview" : "final");
      request.resolution = numberValue(
        request.quality === "final" ? "final-resolution" : "preview-resolution",
      );
      const body = { name: $("profile-name").value, request };
      const saved = await api(
        profile ? `/profiles/${profile.id}` : "/profiles",
        profile ? "PUT" : "POST",
        profile ? { ...body, revision: profile.revision } : body,
      );
      if (context !== profileContext) return;
      profile = saved;
      await refreshProfiles();
      if (context !== profileContext) return;
      updateAvailability();
      $("save-state").textContent =
        generation === editGeneration ? "Saved" : "Unsaved";
      if (generation === editGeneration) message("");
    });
    $("delete-profile").onclick = action(async () => {
      if (!profile) return;
      if (!confirm(`Delete profile “${profile.name}”?`)) return;
      const target = profile, context = profileContext;
      await api(`/profiles/${target.id}`, "DELETE", {
        revision: target.revision,
        confirmed: true,
      });
      if (context === profileContext && profile?.id === target.id) {
        changeProfileContext();
        profile = null;
        $("profile-name").value = "";
        message("Profile deleted");
      }
      await refreshProfiles();
      updateAvailability();
    });
    function numberValue(id) {
      const raw = $(id).value;
      return raw.trim() === "" ? null : Number(raw);
    }
    async function submit(quality) {
      const module = modules.find((m) => m.id === model.moduleId);
      if (!module?.state.enabled || !module.actions?.includes(quality === "final" ? "generate" : "preview"))
        throw Error("Module does not support this action");
      const request = readDraft();
      request.quality = quality;
      request.resolution = numberValue(
        quality === "preview" ? "preview-resolution" : "final-resolution",
      );
      const job = await api("/jobs", "POST", {
        request,
        idempotency_key: crypto.randomUUID(),
      });
      if (quality === "preview") desiredJob = job.id;
      message(
        `${quality === "preview" ? "Preview" : "Generation"} queued`,
        false,
        job.id,
      );
      await pollJobs();
    }
    for (const [id, quality] of [
      ["preview-design", "preview"],
      ["generate-design", "final"],
    ])
      $(id).onclick = action(async () => {
        $(id).disabled = true;
        try {
          await submit(quality);
        } finally {
          updateAvailability();
        }
      });
    const attribution = (job) =>
      `${job.request.geometry_id} · ${job.request.representation} · ${job.request.quality} ${job.request.resolution} · ${job.id.slice(0, 8)}`;
    function renderJobs() {
      const root = $("design-jobs");
      const focused = document.activeElement?.dataset.jobAction;
      root.replaceChildren();
      if (!model.jobs.length) {
        const empty = document.createElement("p");
        empty.className = "hint";
        empty.textContent = "No jobs";
        root.append(empty);
      }
      for (const job of model.jobs) {
        const row = document.createElement("article");
        row.className = "design-job";
        row.dataset.jobId = job.id;
        const text = document.createElement("span");
        text.textContent = attribution(job);
        const state = document.createElement("span");
        state.className = "serial-status";
        state.textContent = job.state;
        row.append(text, state);
        if (job.state === "queued" || job.state === "running") {
          const cancel = button("Cancel", async () => {
            await api(`/jobs/${job.id}/cancel`, "POST");
            await pollJobs();
          });
          cancel.dataset.jobAction = `cancel-${job.id}`;
          row.append(cancel);
        }
        if (job.state === "succeeded") {
          const show = button(
            job.request.quality === "preview" ? "View preview" : "View final",
            () => {
              desiredJob = job.id;
              return showJob(job);
            },
          );
          show.dataset.jobAction = `view-${job.id}`;
          const link = document.createElement("a");
          link.className = "btn mini";
          link.textContent = "Download STL";
          link.href = job.artifact_urls.stl;
          link.dataset.jobAction = `download-${job.id}`;
          row.append(show, link);
        }
        if (job.error) {
          const error = document.createElement("small");
          error.textContent = job.error.message;
          error.className = "design-job-error";
          row.append(error);
        }
        root.append(row);
      }
      if (focused)
        Array.from(root.querySelectorAll("[data-job-action]"))
          .find((e) => e.dataset.jobAction === focused)
          ?.focus({ preventScroll: true });
    }
    async function pollJobs() {
      const token = model.beginJobs();
      const { jobs } = await api("/jobs");
      if (!model.acceptJobs(jobs, token)) return;
      renderJobs();
      const notice = jobs.find((j) => j.id === noticeJob);
      if (notice && !["queued", "running"].includes(notice.state))
        message(
          `${notice.request.quality === "preview" ? "Preview" : "Generation"} ${notice.state}${notice.error ? `: ${notice.error.message}` : ""}`,
          ["failed", "interrupted"].includes(notice.state),
        );
      const selected = jobs.find((j) => j.id === desiredJob);
      if (selected?.state === "succeeded") await showJob(selected);
    }
    function savedCamera() {
      try {
        return JSON.parse(localStorage.getItem("ax4lab.design.camera"));
      } catch {
        return null;
      }
    }
    function makeViewer() {
      const win = vtk.Rendering.Misc.vtkGenericRenderWindow.newInstance({
        background: [0.97, 0.98, 1],
      });
      win.setContainer($("design-viewer"));
      const renderer = win.getRenderer(),
        mapper = vtk.Rendering.Core.vtkMapper.newInstance(),
        actor = vtk.Rendering.Core.vtkActor.newInstance();
      actor.setMapper(mapper);
      actor.getProperty().setColor(0.24, 0.58, 0.72);
      renderer.addActor(actor);
      const camera = renderer.getActiveCamera();
      const saved = savedCamera();
      if (saved) camera.set(saved);
      else {
        camera.setPosition(1, -1, 1);
        camera.setViewUp(0, 0, 1);
      }
      const save = () => {
        try {
          localStorage.setItem(
            "ax4lab.design.camera",
            JSON.stringify({
              position: camera.getPosition(),
              focalPoint: camera.getFocalPoint(),
              viewUp: camera.getViewUp(),
              parallelScale: camera.getParallelScale(),
            }),
          );
        } catch {}
      };
      win.getInteractor().onEndAnimation(save);
      window.addEventListener("pagehide", save);
      new ResizeObserver(() => win.resize()).observe($("design-viewer"));
      return { win, renderer, mapper, camera, save, hasCamera: Boolean(saved) };
    }
    const loadArtifact = createArtifactLoader(async (url) => {
      const response = await fetch(url);
      if (!response.ok) {
        let error;
        try {
          error = await response.json();
        } catch {}
        throw Error(error ? errorMessage(error) : "Artifact unavailable");
      }
      return response.arrayBuffer();
    });
    async function showJob(job) {
      if (loadedJob === job.id) return;
      const token = ++assetToken;
      const data = await loadArtifact(job.artifact_urls.stl);
      if (token !== assetToken || desiredJob !== job.id) return;
      if (!viewer) viewer = makeViewer();
      const reader = vtk.IO.Geometry.vtkSTLReader.newInstance();
      reader.parseAsArrayBuffer(data);
      const poly = reader.getOutputData();
      if (!poly?.getNumberOfPoints()) throw Error("Empty STL");
      viewer.mapper.setInputData(poly);
      if (!viewer.hasCamera) {
        viewer.renderer.resetCamera();
        viewer.hasCamera = true;
      }
      viewer.renderer.resetCameraClippingRange();
      viewer.win.resize();
      viewer.win.getRenderWindow().render();
      viewer.save();
      reader.delete();
      loadedJob = job.id;
      $("result-title").textContent = attribution(job);
      $("design-viewer").dataset.jobId = job.id;
      $("result-download").href = job.artifact_urls.stl;
      $("result-download").hidden = false;
      $("viewer-empty").hidden = true;
      const receipt = job.receipt,
        checks = receipt.checks;
      $("result-checks").textContent =
        `${receipt.final_geometry_valid ? "Final geometry valid" : "Preview only"} · Watertight: ${checks.watertight ? "Yes" : "No"} · Volume fraction: ${(receipt.volume_fraction * 100).toFixed(1)}% · Manufacturing ready: No`;
    }
    $("reset-camera").onclick = () => {
      if (viewer) {
        viewer.camera.setPosition(1, -1, 1);
        viewer.camera.setFocalPoint(0, 0, 0);
        viewer.camera.setViewUp(0, 0, 1);
        viewer.renderer.resetCamera();
        viewer.win.getRenderWindow().render();
        viewer.save();
      }
    };
    $("design-viewer").onkeydown = (event) => {
      if (!viewer) return;
      const c = viewer.camera;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight")
        c.azimuth(event.key === "ArrowLeft" ? -15 : 15);
      else if (event.key === "ArrowUp" || event.key === "ArrowDown")
        c.elevation(event.key === "ArrowUp" ? 15 : -15);
      else if (event.key === "+" || event.key === "=") c.dolly(1.15);
      else if (event.key === "-") c.dolly(1 / 1.15);
      else if (event.key.toLowerCase() === "r") {
        $("reset-camera").click();
        return;
      } else return;
      event.preventDefault();
      c.orthogonalizeViewUp();
      viewer.renderer.resetCameraClippingRange();
      viewer.win.getRenderWindow().render();
      viewer.save();
    };
    action(async () => {
      const data = await api("/modules");
      modules = data.modules;
      renderModules();
      await refreshProfiles();
      await pollJobs();
      if (data.errors.length)
        message(data.errors.map((e) => e.message).join("; "), true);
    })();
    let timer;
    async function tick() {
      try {
        if (!document.hidden) await pollJobs();
      } catch (error) {
        message(error.message, true);
      }
      timer = setTimeout(tick, 1500);
    }
    timer = setTimeout(tick, 1500);
    window.addEventListener("pagehide", () => clearTimeout(timer));
  }
  return {
    parameters,
    orientationAxes,
    errorMessage,
    createModel,
    createArtifactLoader,
    boot,
  };
});
