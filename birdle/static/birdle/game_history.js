// game_history.js

import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

export function game_history(history, div_id) {
    const results = ["Win", "Loss", "Did not play"]

    Date.prototype.addDays = function(days) {
        var date = new Date(this.valueOf());
        date.setDate(date.getDate() + days);
        return date;
    };

    function getDates(startDate, stopDate) {
        var dateArray = new Array();
        var currentDate = startDate;
        while (currentDate <= stopDate) {
            let res = results[Math.floor(Math.random()*results.length)]
            dateArray.push({Date: (new Date(currentDate)).toISOString().split('T')[0], Result: res});
            currentDate = currentDate.addDays(1);
        }
        return dateArray;
    }; 

    //const cal = getDates(new Date("2023-01-01"), new Date());
    const cal = history;

    const cal_plot = Plot.plot({
        //x: {tickFormat: Plot.formatWeekday(), tickSize: 0, anchor: "top"},
        x: {axis: null},
        y: {axis: null},
        //fx: {tickFormat: Plot.formatMonth("en", "short"), anchor: "bottom"},
        color: {type: "categorical", range: ["skyblue", "#FFB000", "#e9ecef"], legend: true, label: "Daily Result", domain: ["Win", "Loss", "Did not play"]},
        marginTop: 60,
        padding: 0,
        marks: [
        Plot.cell(cal, {
            x: (d) => (new Date(d.Date)).getUTCDay(),
            fy: (d) => (new Date(d.Date)).getUTCMonth(),
            fx: (d) => (new Date(d.Date)).getUTCFullYear(),
            y: (d) => d3.utcWeek.count(d3.utcMonth(new Date(d.Date)), new Date(d.Date)),
            fill: (d) => d.Result,
            text: (d) => (new Date(d.Date)).getUTCDate(),
            stroke: (d) => "#6c757d"
        }),
        Plot.text(cal, {
            x: (d) => (new Date(d.Date)).getUTCDay(),
            fy: (d) => (new Date(d.Date)).getUTCMonth(),
            fx: (d) => (new Date(d.Date)).getUTCFullYear(),
            y: (d) => d3.utcWeek.count(d3.utcMonth(new Date(d.Date)), new Date(d.Date)),
            text: (d) => (new Date(d.Date)).getUTCDate()
        }),
        Plot.axisX({tickFormat: Plot.formatWeekday("en", "narrow"), tickSize: 0, anchor: "top"}),
        Plot.axisFx({tickFormat: (d) => d.toLocaleString(undefined, {useGrouping: false}), anchor: "top", fontWeight: "bold", tickPadding: 30}),
        Plot.axisFy({tickFormat: Plot.formatMonth("en", "short"), anchor: "left", fontWeight: "bold"}),
        Plot.tip(cal, Plot.pointer({
            x: (d) => (new Date(d.Date)).getUTCDay(),
            fy: (d) => (new Date(d.Date)).getUTCMonth(),
            y: (d) => d3.utcWeek.count(d3.utcMonth(new Date(d.Date)), new Date(d.Date)),
            title: (d) => `${d.Date}: ${d.Result}`
        }))
        ]
    });
    const div = document.querySelector(div_id);
    div.append(cal_plot);
};


