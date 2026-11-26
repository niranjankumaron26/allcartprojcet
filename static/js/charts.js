if (window.Chart) {
  document.querySelectorAll("[data-chart]").forEach(source => {
    const rows = JSON.parse(source.textContent);
    new Chart(document.getElementById(source.dataset.chart), {
      type: source.dataset.kind,
      data: {labels: rows.map(row => row.label), datasets: [{
        data: rows.map(row => Number(row.amount)),
        backgroundColor: "#d96c4c", borderRadius: 5
      }]},
      options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}},
        scales: {y: {beginAtZero: true}}}
    });
  });
}
