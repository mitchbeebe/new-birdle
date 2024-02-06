// guess_distribution.js

import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

export function guess_distribution(data, div_id) {
    const plot = Plot.plot({
        height: 300,
        marks: [
            Plot.barX(data, {x: "count", y: "guesses"}),
            Plot.text(data, {x: "count", y: "guesses", text: (d) => (d.count), dx: -10, fill: "white", fontSize: 18}),
            Plot.axisY({label: "Guess Count", fontSize: 18, labelAnchor: "top", labelArrow: "down"}),
            Plot.axisX({label: "Games Won", ticks: 0, fontSize: 18, labelAnchor: "left"}),
            Plot.ruleX([0])
        ]});
    const div = document.querySelector(div_id);
    div.append(plot);
};


