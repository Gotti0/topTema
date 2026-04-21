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

    // 트리맵 렌더링 (가독성 개선 버전)
    function renderHeatmap(data) {
        const seriesData = data.map(item => {
            const val = item.value;
            let color = '#475569'; // Neutral (Slate 600)
            if (val <= -3) color = '#b91c1c'; // Red 700
            else if (val < -1) color = '#ef4444'; // Red 500
            else if (val >= 3) color = '#15803d'; // Green 700
            else if (val > 1) color = '#22c55e'; // Green 500

            return {
                x: item.name,
                y: Math.abs(val) || 0.5, // 너무 작으면 글자가 안 보이므로 최소값 상향
                actualValue: val,
                themeId: item.id,
                fillColor: color
            };
        });

        const options = {
            series: [{ data: seriesData }],
            chart: {
                height: 550, // 높이 상향
                type: 'treemap',
                events: {
                    dataPointSelection: (event, chartContext, config) => {
                        const item = options.series[config.seriesIndex].data[config.dataPointIndex];
                        loadThemeStocks(item.themeId, item.x);
                    }
                },
                toolbar: { show: false }
            },
            dataLabels: { 
                enabled: true,
                style: {
                    fontSize: '11px',
                    fontWeight: 'bold',
                    fontFamily: 'Pretendard, sans-serif'
                },
                formatter: function(text, op) {
                    const val = op.value;
                    const actualValue = op.w.config.series[op.seriesIndex].data[op.dataPointIndex].actualValue;
                    // 셀이 너무 작으면 텍스트 숨김 (가독성 확보)
                    if (op.value < 1.0) return ''; 
                    return [text, actualValue + "%"];
                },
                offsetY: -2
            },
            plotOptions: {
                treemap: {
                    enableShades: false, // 단색으로 대비 명확화
                    distributed: true,
                    useFillColorAsStroke: false
                }
            },
            stroke: {
                show: true,
                width: 2,
                colors: ['#0f172a'] // 배경색과 동일한 선으로 구분감 부여
            },
            legend: { show: false },
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
    await fetchDates();
    fetchThemes();
});
ement('div');
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
