/* Declarative workspace fields. Visibility affects presentation, never submission. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WorkspaceFields = api;
})(globalThis, function () {
  "use strict";
  function visible(field, values) {
    const c = field.visible_when;
    return (
      !c ||
      ("equals" in c
        ? JSON.stringify(values[c.field]) === JSON.stringify(c.equals)
        : c.in.some(
            (v) => JSON.stringify(v) === JSON.stringify(values[c.field]),
          ))
    );
  }
  function render(container, fields, values, onChange = () => {}) {
    const doc = container.ownerDocument,
      controls = {},
      rows = {};
    container.replaceChildren();
    const number = (el) => (el.value.trim() === "" ? null : Number(el.value));
    function read() {
      return Object.fromEntries(
        fields.map((f) => {
          const inputs = controls[f.key];
          return [
            f.key,
            f.type === "vector"
              ? inputs.map(number)
              : f.type === "boolean"
                ? inputs[0].checked
                : ["number", "integer"].includes(f.type)
                  ? number(inputs[0])
                  : inputs[0].value,
          ];
        }),
      );
    }
    function update() {
      const values = read();
      fields.forEach((f) => (rows[f.key].hidden = !visible(f, values)));
      onChange(values);
    }
    for (const field of fields) {
      const row = doc.createElement(
        field.type === "vector" ? "fieldset" : "label",
      );
      rows[field.key] = row;
      const title = doc.createElement(
        field.type === "vector" ? "legend" : "span",
      );
      title.textContent = field.label + (field.unit ? ` (${field.unit})` : "");
      row.append(title);
      const inputs = [],
        group = field.type === "vector" ? doc.createElement("div") : row;
      if (group !== row) {
        group.className = "workspace-vector";
        row.append(group);
      }
      for (let i = 0; i < (field.type === "vector" ? field.length : 1); i++) {
        const el = doc.createElement(
          field.type === "enum" ? "select" : "input",
        );
        el.name = field.key;
        el.dataset.field = field.key;
        el.setAttribute(
          "aria-label",
          field.label + (field.type === "vector" ? ` ${i + 1}` : ""),
        );
        if (field.type === "enum") {
          for (const option of field.options) {
            const item = doc.createElement("option");
            item.value = option;
            item.textContent = option;
            el.append(item);
          }
        } else {
          el.type =
            field.type === "boolean"
              ? "checkbox"
              : ["number", "integer", "vector"].includes(field.type)
                ? "number"
                : "text";
          if (el.type === "number") {
            el.min = String(field.min);
            el.max = String(field.max);
            el.step = String(
              field.step ?? (field.type === "integer" ? 1 : "any"),
            );
          }
        }
        const value =
          field.type === "vector" ? values[field.key]?.[i] : values[field.key];
        if (field.type === "boolean") el.checked = Boolean(value);
        else el.value = value == null ? "" : String(value);
        el.addEventListener("input", update);
        el.addEventListener("change", update);
        inputs.push(el);
        group.append(el);
      }
      controls[field.key] = inputs;
      container.append(row);
    }
    fields.forEach((f) => (rows[f.key].hidden = !visible(f, read())));
    return { read, rows, controls };
  }
  return { render, visible };
});
