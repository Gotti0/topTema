document.addEventListener('DOMContentLoaded', async () => {
    const heatmapEl = document.querySelector("#heatmap-chart");
    const top10El = document.querySelector("#top10-chart");
    const stockListEl = document.querySelector("#stock-list");
    const themeTableBody = document.querySelector("#theme-table-body");
    const selectedThemeName = document.querySelector("#selected-theme-name");
    const dateInput = document.querySelector("#date-select");
    const liveBtn = document.querySelector("#live-btn");

    let heatmapChart = null;
    let top10Chart = null;

    // 1. 이벤트 위임: 테이블의 모든 클릭 이벤트를 부모(tbody)에서 처리
    themeTableBody.addEventListener('click', (e) => {
        const row = e.target.closest('tr');
        if (row && row.dataset.themeId) {
            loadThemeStocks(row.dataset.themeId, row.dataset.themeName);
        }
    });

    async function setupDatePicker() {
        try {
            const response = await fetch('/api/history/dates');
            const dates = await response.json();
            if (dates.length > 0) {
                const maxDate = dates[0];
                const minDate = dates[dates.length - 1];
                dateInput.max = `${maxDate.substring(0,4)}-${maxDate.substring(4,6)}-${maxDate.substring(6,8)}`;
                dateInput.min = `${minDate.substring(0,4)}-${minDate.substring(4,6)}-${minDate.substring(6,8)}`;
            }
        } catch (error) {
            console.error('Error fetching dates:', error);
        }
    }

    async function fetchThemes(date = "") {
        try {
            const formattedDate = date.replace(/-/g, "");
            const url = formattedDate ? `/api/themes?date=${formattedDate}` : '/api/themes';
            const response = await fetch(url);
            const data = await response.json();
            renderHeatmap(data);
            renderThemeTable(data);
        } catch (error) {
            console.error('Error fetching themes:', error);
        }
    }

    dateInput.addEventListener('change', (e) => {
        if (e.target.value) fetchThemes(e.target.value);
    });

    liveBtn.addEventListener('click', () => {
        dateInput.value = "";
        fetchThemes("");
    });

    // 2. 차트 최적화: destroy 대신 updateSeries/updateOptions 사용
    function renderHeatmap(data) {
        const seriesData = data.map(item => {
            const val = item.value;
            let color = '#475569'; 
            if (val <= -3) color = '#b91c1c'; 
            else if (val < -1) color = '#ef4444'; 
            else if (val >= 3) color = '#15803d'; 
            else if (val > 1) color = '#22c55e'; 

            return {
                x: item.name,
                y: Math.abs(val) || 0.5,
                actualValue: val,
                themeId: item.id,
                fillColor: color
            };
        });

        const options = {
            series: [{ data: seriesData }],
            chart: {
                height: 550,
                type: 'treemap',
                events: {
                    dataPointSelection: (event, chartContext, config) => {
                        const item = config.w.config.series[config.seriesIndex].data[config.dataPointIndex];
                        loadThemeStocks(item.themeId, item.x);
                    }
                },
                toolbar: { show: false },
                animations: { enabled: true, easing: 'easeinout', speed: 800 }
            },
            dataLabels: { 
                enabled: true,
                style: { fontSize: '11px', fontWeight: 'bold' },
                formatter: (text, op) => {
                    const actualValue = op.w.config.series[op.seriesIndex].data[op.dataPointIndex].actualValue;
                    return op.value < 1.0 ? '' : [text, actualValue + "%"];
                }
            },
            plotOptions: { treemap: { enableShades: false, distributed: true } },
            stroke: { show: true, width: 2, colors: ['#0f172a'] },
            theme: { mode: 'dark' }
        };

        if (heatmapChart) {
            // 인스턴스가 있으면 데이터와 옵션만 업데이트 (깜빡임 방지)
            heatmapChart.updateOptions(options);
        } else {
            heatmapChart = new ApexCharts(heatmapEl, options);
            heatmapChart.render();
        }
    }

    // 3. DOM 최적화: DocumentFragment를 사용하여 일괄 렌더링
    function renderThemeTable(data) {
        const fragment = document.createDocumentFragment();
        
        data.sort((a, b) => b.value - a.value).forEach(item => {
            const row = document.createElement('tr');
            row.className = 'border-b border-slate-800 hover:bg-slate-800 cursor-pointer transition-colors';
            // 데이터 속성 부여 (이벤트 위임용)
            row.dataset.themeId = item.id;
            row.dataset.themeName = item.name;
            
            row.innerHTML = `
                <td class="py-3 px-4">${item.name}</td>
                <td class="py-3 px-4 text-right ${item.value > 0 ? 'text-green-400' : 'text-red-400'}">${item.value}%</td>
                <td class="py-3 px-4 text-right text-slate-400">${item.stk_num}</td>
                <td class="py-3 px-4 text-slate-400 text-sm">${item.main_stk}</td>
            `;
            fragment.appendChild(row);
        });

        themeTableBody.innerHTML = '';
        themeTableBody.appendChild(fragment);
    }

    async function loadThemeStocks(themeId, themeName) {
        selectedThemeName.innerText = themeName;
        stockListEl.innerHTML = '<p class="text-slate-500 text-center py-4">Loading...</p>';
        
        try {
            const date = dateInput.value.replace(/-/g, "");
            const url = date ? `/api/themes/${themeId}/stocks?date=${date}` : `/api/themes/${themeId}/stocks`;
            const response = await fetch(url);
            const stocks = await response.json();
            
            if (!stocks || stocks.length === 0) {
                if (top10Chart) top10Chart.destroy();
                top10Chart = null;
                stockListEl.innerHTML = '<p class="text-slate-500 text-center py-4">데이터가 없습니다.</p>';
                return;
            }
            
            renderTop10Chart(stocks);
            renderStockList(stocks);
        } catch (error) {
            console.error('Error fetching stocks:', error);
        }
    }

    function renderTop10Chart(stocks) {
        const options = {
            series: [{
                name: '등락율',
                data: stocks.map(s => parseFloat(s.change_rt.replace('%', '')))
            }],
            chart: { type: 'bar', height: 300, toolbar: { show: false } },
            plotOptions: { bar: { borderRadius: 4, horizontal: true, distributed: true } },
            dataLabels: { enabled: true, formatter: (val) => val + "%" },
            xaxis: { 
                categories: stocks.map(s => s.name),
                labels: { formatter: (val) => val + "%" }
            },
            theme: { mode: 'dark' },
            colors: stocks.map(s => parseFloat(s.change_rt) > 0 ? '#22c55e' : '#ef4444')
        };

        if (top10Chart) {
            top10Chart.updateOptions(options);
        } else {
            top10Chart = new ApexCharts(top10El, options);
            top10Chart.render();
        }
    }

    function renderStockList(stocks) {
        const fragment = document.createDocumentFragment();
        stocks.forEach(s => {
            const item = document.createElement('div');
            item.className = 'flex justify-between items-center p-3 bg-slate-800 rounded-md mb-2';
            const changeVal = parseFloat(s.change_rt);
            const colorClass = changeVal > 0 ? 'text-green-400' : (changeVal < 0 ? 'text-red-400' : 'text-slate-400');
            const cleanCode = s.code.split('_')[0];
            const cleanPrice = s.price === "N/A" ? "과거 기록" : s.price.replace('+', '').toLocaleString();

            item.innerHTML = `
                <div><span class="font-medium">${s.name}</span><span class="text-xs text-slate-500 ml-2">${cleanCode}</span></div>
                <div class="text-right"><div class="${colorClass} font-bold">${s.change_rt}</div><div class="text-xs text-slate-400">${cleanPrice}</div></div>
            `;
            fragment.appendChild(item);
        });
        stockListEl.innerHTML = '';
        stockListEl.appendChild(fragment);
    }

    await setupDatePicker();
    fetchThemes("");
});
