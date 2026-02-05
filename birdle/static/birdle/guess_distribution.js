// guess_distribution.js

import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

export function guess_distribution(data, div_id) {
    const div = document.querySelector(div_id);

    // Check if there's any data to display
    const hasData = data.length > 0 && data.some(d => d.count > 0);

    if (!hasData) {
        const msg = document.createElement("p");
        msg.className = "text-muted";
        msg.textContent = "No wins yet. Keep playing!";
        div.append(msg);
        return;
    }

    const plot = Plot.plot({
        height: 300,
        marks: [
            Plot.barX(data, {x: "count", y: "guesses"}),
            Plot.text(data, {x: "count", y: "guesses", text: (d) => (d.count), dx: -10, fill: "white", fontSize: 18}),
            Plot.axisY({label: "Guess Count", fontSize: 18, labelAnchor: "top", labelArrow: "down"}),
            Plot.axisX({label: "Games Won", ticks: 0, fontSize: 18, labelAnchor: "left", labelArrow: "right"}),
            Plot.ruleX([0])
        ]});
    div.append(plot);
};


