let summaryChart = null;
let trendChart = null;

document.querySelector('[data-tab="data"]').addEventListener('click', () => {
  setTimeout(loadChart, 200);
});

async function loadChart(days) {
  const daysParam = days || '7';
  try {
    const data = await api('/api/stats/daily?days=' + daysParam);
    initSummaryChart(data.stats || []);
    initTrendChart(data.stats || []);
  } catch (e) {
    console.error('图表加载失败:', e);
  }
}

function initSummaryChart(stats) {
  const el = document.getElementById('chartSummary');
  if (!el) return;
  if (summaryChart) summaryChart.dispose();
  summaryChart = echarts.init(el);

  const days = [...new Set(stats.map(s => s.day))].slice(-7);
  const counts = days.map(d => {
    const dayStats = stats.filter(s => s.day === d);
    return dayStats.reduce((sum, s) => sum + s.event_count, 0);
  });

  summaryChart.setOption({
    title: { text: '每日事件量', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: days, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: counts,
      itemStyle: { color: '#1976D2', borderRadius: [4, 4, 0, 0] },
      barMaxWidth: 40,
    }],
  });
}

function initTrendChart(stats) {
  const el = document.getElementById('chartTrend');
  if (!el) return;
  if (trendChart) trendChart.dispose();
  trendChart = echarts.init(el);

  const days = [...new Set(stats.map(s => s.day))].slice(-7);
  const sessionIds = [...new Set(stats.map(s => s.session_id))].slice(0, 5);

  const series = sessionIds.map(sid => {
    const data = days.map(d => {
      const match = stats.find(s => s.day === d && s.session_id === sid);
      return match ? match.event_count : 0;
    });
    return {
      name: sid.slice(0, 12),
      type: 'line',
      smooth: true,
      data,
      symbolSize: 6,
    };
  });

  trendChart.setOption({
    title: { text: '会话趋势对比', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: { type: 'category', data: days, boundaryGap: false },
    yAxis: { type: 'value' },
    series,
  });
}

window.addEventListener('resize', () => {
  if (summaryChart) summaryChart.resize();
  if (trendChart) trendChart.resize();
});
