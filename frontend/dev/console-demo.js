(async () => {
  // 仅当前页面有效；刷新后恢复。所有数据均为虚构，不发送登录或业务请求。
  const today = new Date().toISOString().slice(0, 10);
  const nurse = { nurse_id: 'console-demo', nurse_code: 'DEMO', name: '测试护士', role: 'nurse', permissions: ['query_patient'] };
  const schedules = ['测试内科', '测试外科'].map((name, i) => ({ schedule_id: `demo-${i}`, clinic_dept: `DEMO-D${i}`, clinic_label: name, dept_name: name, time_desc: '上午', registration_limits: 30, registration_num: 4 }));
  const patients = ['王小明', '王小明', '王芳', '李明'].map((name, i) => ({
    registration_id: `demo-reg-${i}`, patient_id: `DEMO-P${i}`, visit_no: `DEMO-V${i}`, card_id: `DEMO-C${i}`,
    name, sex: i === 2 ? '女' : '男', age: 30 + i, charge_type: '自费', serial_no: i + 1, pnum: i + 1,
    telephone: i === 3 ? '' : `测试电话-${i + 1}`, registration_status: ['已就诊', '候诊', '已就诊', ''][i],
    fre_date: i % 2 === 0 ? `${today} 08:30:00` : null, visit_date: today, visit_time_desc: '上午', clinic_label: '测试内科'
  }));
  if (!window.__nurseDemoOriginalFetch) window.__nurseDemoOriginalFetch = window.fetch;
  const demoPins = new Map();
  window.fetch = async (input, options = {}) => {
    const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(rawUrl, location.protocol === 'file:' ? 'http://localhost/' : location.href);
    const apiPath = url.pathname.replace(/^\/[A-Za-z]:(?=\/api\/)/, '');
    const ok = data => new Response(JSON.stringify({ success: true, data, message: '本地模拟数据' }), { headers: { 'Content-Type': 'application/json' } });
    switch (apiPath) {
      case '/api/v1/auth/login': case '/api/v1/auth/current': return ok(nurse);
      case '/api/v1/auth/logout': return ok(null);
      case '/api/v1/pinned-schedules': {
        const method = options.method || 'GET';
        if (method === 'GET') return ok({ pins: [...demoPins.values()] });
        const schedule = schedules.find(s => s.schedule_id === JSON.parse(options.body).schedule_id);
        if (!schedule) throw new Error('模拟排班不存在');
        const key = JSON.stringify([schedule.clinic_dept, schedule.clinic_label, schedule.time_desc]);
        if (method === 'PUT') demoPins.set(key, schedule); else demoPins.delete(key);
        return ok({ pinned: method === 'PUT' });
      }
      case '/api/v1/clinic-schedules': return ok({ schedules, dept_groups: schedules.map(s => ({ dept_name: s.dept_name, schedules: [s] })) });
      case '/api/v1/patient-registrations': {
        const q = url.searchParams.get('keyword') || '';
        const rows = patients.filter(p => p.name.includes(q) || p.card_id === q).map(p => ({ ...p, clinic_label: url.searchParams.get('clinic_label') || p.clinic_label }));
        return ok({ registrations: rows, total_count: rows.length, source: 'demo' });
      }
      case '/api/v1/patient-orders': return ok({ class_groups: {}, orders: [] });
      case '/api/v1/patient-query/search': {
        const type = url.searchParams.get('query_type'), q = url.searchParams.get('query_value') || '';
        const rows = patients.filter(p => type === 'name' ? p.name.includes(q) : p[type] === q)
          .filter(p => (!url.searchParams.get('start_date') || p.visit_date >= url.searchParams.get('start_date')) && (!url.searchParams.get('end_date') || p.visit_date <= url.searchParams.get('end_date')));
        const visits = rows.map(p => ({ ...p, patient_name: p.name, dept_name: p.clinic_label, orders: [], order_count: 0, cmc_count: 0 }));
        return ok({ patient_info: rows.length === 1 ? rows[0] : null, multiple_patients: rows.length > 1, visits, total_count: visits.length, can_query_prescription: false });
      }
      default: throw new Error(`模拟模式未实现此请求，已阻止发送：${url.pathname}`);
    }
  };
  window.stopNurseDemo = () => { window.fetch = window.__nurseDemoOriginalFetch; delete window.__nurseDemoOriginalFetch; sessionStorage.removeItem('nurseInfo'); console.info('模拟已停止，请刷新页面。'); };
  if (typeof checkLogin === 'function') {
    const loggedIn = await checkLogin();
    if (loggedIn === false) throw new Error('模拟登录失败，请检查 Console 中前一条错误');
  }
  if (typeof showMainPage === 'function') {
    showMainPage();
    await loadClinicSchedules();
    selectSchedule('测试内科', '上午', '测试内科');
  }
  console.info('模拟已开启：4位患者，已报到2位、未报到2位、已就诊2位；姓名搜“王”命中3位。刷新或导航后需重新运行；stopNurseDemo() 停止。');
})();
