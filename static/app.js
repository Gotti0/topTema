document.addEventListener('DOMContentLoaded', async () => {
    const heatmapEl = document.querySelector("#heatmap-chart");
    const top10El = document.querySelector("#top10-chart");
    const stockListEl = document.querySelector("#stock-list");
    const themeTableBody = document.querySelector("#theme-table-body");
    const selectedThemeName = document.querySelector("#selected-theme-name");

    let heatmapChart = null;
    let top10Chart = null;

    // 테마 데이터 가져오기
    async function fetchThemes() {
        try {
            const response = await fetch('/api/themes');
            const data = await response.json();
            renderHeatmap(data);
            renderThemeTable(data);
        } catch (error) {
            console.error('Error fetching themes:', error);
        }
    }

    // 히트맵 렌더링
    function renderHeatmap(data) {
        // 데이터를 ApexCharts Heatmap 포맷으로 변환
        // 예: [{ name: 'Range 1', data: [{x: 'Theme A', y: 1.2}] }]
        const series = [];
        const itemsPerSeries = Math.ceil(data.length / 5);
        
        for (let i = 0; i < 5; i++) {
            const chunk = data.slice(i * itemsPerSeries, (i + 1) * itemsPerSeries);
            if (chunk.length === 0) continue;
            
            series.push({
                name: `Group ${i + 1}`,
                data: chunk.map(item => ({
                    x: item.name,
                    y: item.value,
                    themeId: item.id
                }))
            });
        }

        const options = {
            series: series,
            chart: {
                height: 450,
                type: 'heatmap',
                events: {
                    dataPointSelection: (event, chartContext, config) => {
                        const item = series[config.seriesIndex].data[config.dataPointIndex];
                        loadThemeStocks(item.themeId, item.x);
                    }
                },
                toolbar: { show: false }
            },
            dataLabels: { enabled: false },
            colors: ["#ef4444", "#22c55e"], // Red to Green
            plotOptions: {
                heatmap: {
                    shadeIntensity: 0.5,
                    colorScale: {
                        ranges: [
                            { from: -100, to: -3, color: '#991b1b', name: 'Very Low' },
                            { from: -3, to: -1, color: '#ef4444', name: 'Low' },
                            { from: -1, to: 1, color: '#64748b', name: 'Neutral' },
                            { from: 1, to: 3, color: '#22c55e', name: 'High' },
                            { from: 3, to: 100, color: '#166534', name: 'Very High' }
                        ]
                    }
                }
            },
            xaxis: { labels: { show: false } },
            theme: { mode: 'dark' }
        };

        if (heatmapChart) heatmapChart.destroy();
        heatmapChart = new ApexCharts(heatmapEl, options);
        heatmapChart.render();
    }

    // 테마 리스트 테이블 렌더링
    function renderThemeTable(data) {
        themeTableBody.innerHTML = '';
        data.sort((a, b) => b.value - a.value).forEach(item => {
            const row = document.createElement('tr');
            row.className = 'border-b border-slate-800 hover:bg-slate-800 cursor-pointer transition-colors';
            row.innerHTML = `
                <td class="py-3 px-4">${item.name}</td>
                <td class="py-3 px-4 text-right ${item.value > 0 ? 'text-green-400' : 'text-red-400'}">${item.value}%</td>
                <td class="py-3 px-4 text-right text-slate-400">${item.stk_num}</td>
                <td class="py-3 px-4 text-slate-400 text-sm">${item.main_stk}</td>
            `;
            row.onclick = () => loadThemeStocks(item.id, item.name);
            themeTableBody.appendChild(row);
        });
    }

    // 특정 테마 종목 로드
    async function loadThemeStocks(themeId, themeName) {
        selectedThemeName.innerText = themeName;
        stockListEl.innerHTML = '<p class="text-slate-500">Loading...</p>';
        
        try {
            const response = await fetch(`/api/themes/${themeId}/stocks`);
            const stocks = await response.json();
            renderTop10Chart(stocks);
            renderStockList(stocks);
        } catch (error) {
            console.error('Error fetching stocks:', error);
        }
    }

    // Top 10 바 차트 렌더링
    function renderTop10Chart(stocks) {
        const options = {
            series: [{
                name: '등락율',
                data: stocks.map(s => parseFloat(s.change_rt.replace('%', '')))
            }],
            chart: { type: 'bar', height: 300, toolbar: { show: false } },
            plotOptions: {
                bar: {
                    borderRadius: 4,
                    horizontal: true,
                    distributed: true
                }
            },
            dataLabels: { enabled: false },
            xaxis: {
                categories: stocks.map(s => s.name),
                labels: { style: { colors: '#94a3b8' } }
            },
            yaxis: {
                labels: { style: { colors: '#94a3b8' } }
            },
            legend: { show: false },
            theme: { mode: 'dark' },
            colors: stocks.map(s => parseFloat(s.change_rt) > 0 ? '#22c55e' : '#ef4444')
        };

        if (top10Chart) top10Chart.destroy();
        top10Chart = new ApexCharts(top10El, options);
        top10Chart.render();
    }

    // 종목 상세 리스트 렌더링
    function renderStockList(stocks) {
        stockListEl.innerHTML = '';
        stocks.forEach(s => {
            const item = document.createElement('div');
            item.className = 'flex justify-between items-center p-3 bg-slate-800 rounded-md';
            const changeVal = parseFloat(s.change_rt);
            const colorClass = changeVal > 0 ? 'text-green-400' : (changeVal < 0 ? 'text-red-400' : 'text-slate-400');
            
            item.innerHTML = `
                <div>
                    <span class="font-medium">${s.name}</span>
                    <span class="text-xs text-slate-500 ml-2">${s.code}</span>
                </div>
                <div class="text-right">
                    <div class="${colorClass} font-bold">${s.change_rt}</div>
                    <div class="text-xs text-slate-400">${s.price}</div>
                </div>
            `;
            stockListEl.appendChild(item);
        });
    }

    // 초기 로드
    fetchThemes();
});
