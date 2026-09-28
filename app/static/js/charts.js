// Renders every element with data-chart-src: fetch the figure JSON built by
// app/charts.py, then Plotly.newPlot. Loaded as an external file (CSP
// script-src 'self'); never inserts markup, only textContent.
(function () {
  "use strict";

  function textColor() {
    var value = getComputedStyle(document.documentElement).getPropertyValue("--text");
    return value.trim() || "#1d232b";
  }

  function fail(el) {
    el.textContent = "Chart unavailable";
    el.classList.add("chart-failed");
  }

  function render(el) {
    fetch(el.getAttribute("data-chart-src"), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (fig) {
        var layout = fig.layout || {};
        layout.font = Object.assign({}, layout.font, { color: textColor() });
        el.textContent = "";
        return window.Plotly.newPlot(el, fig.data || [], layout, {
          responsive: true,
          displaylogo: false
        });
      })
      .catch(function () {
        fail(el);
      });
  }

  var charts = document.querySelectorAll("[data-chart-src]");
  Array.prototype.forEach.call(charts, render);

  // Follow an OS light/dark switch without a reload.
  if (window.matchMedia) {
    var scheme = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () {
      Array.prototype.forEach.call(charts, function (el) {
        if (el.classList.contains("js-plotly-plot")) {
          window.Plotly.relayout(el, { "font.color": textColor() });
        }
      });
    };
    if (scheme.addEventListener) {
      scheme.addEventListener("change", onChange);
    }
  }
})();
