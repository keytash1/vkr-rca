/* Optional trusted-local workspace. No model HTML, Markdown or tool commands. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const activeStates = new Set(['queued', 'running', 'cancelling']);
  const labels = {queued:'В очереди', running:'Помощник работает…', cancelling:'Останавливаем…',
    completed:'Готово', partial:'Частичный результат', failed:'Помощник недоступен',
    cancelled:'Остановлено', interrupted:'Прервано при перезапуске'};
  const families = {cpu:'CPU', memory:'памяти', network:'сетевого трафика', traffic_rate:'входного трафика'};
  let config = null, analysis = null, session = null, snapshot = null, timer = null, generation = 0, restoring = false;
  const drafts = new Map();
  let downloadUrl = null;
  function clearDownload() {
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl=null;
    const box=el('export-download');
    if (box) { box.replaceChildren(); box.hidden=true; }
  }
  function prepareDownload(body,filename,type) {
    clearDownload();
    const box=el('export-download'), link=document.createElement('a');
    downloadUrl=URL.createObjectURL(new Blob([body],{type}));
    link.href=downloadUrl; link.download=filename; link.textContent=`Скачать ${filename}`;
    box.append(document.createTextNode('Файл подготовлен. Если загрузка не началась: '),link);
    box.hidden=false;
    // Keep the attached link and URL alive for browsers which defer the download.
    // At most one export URL exists; navigation/editing/new export releases it.
    link.click();
  }
  async function exportInvestigation() {
    try {
      if (!sameRecord(readRecord(),session.record)) throw new Error('Перед экспортом сохраните изменения карточки.');
      const identifier=session.id, version=generation, savedSnapshot=snapshot;
      const markdown=el('export-format').value==='markdown';
      const value=await api(`/api/v2/investigations/${identifier}`);
      if (version!==generation || session?.id!==identifier) return;
      if (value.revision!==session.revision || !sameRecord(readRecord(),value.record))
        throw new Error('Карточка изменилась. Сохраните или заново откройте её перед экспортом.');
      const body=markdown ? investigationMarkdown(value,savedSnapshot) : JSON.stringify({schema_version:'investigation-export-v1',investigation:value,snapshot:savedSnapshot},null,2);
      prepareDownload(body,`investigation-${value.id}.${markdown ? 'md' : 'json'}`,
        markdown ? 'text/markdown;charset=utf-8' : 'application/json');
    } catch (reason) { message(reason); }
  }
  // Object key order is not a change: API/SQLite JSON may reorder action fields.
  function stable(value) {
    if (Array.isArray(value)) return value.map(stable);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));
    return value;
  }
  function sameRecord(left,right) { return JSON.stringify(stable(left))===JSON.stringify(stable(right)); }

  function message(reason) {
    const box = el('investigation-error'); box.hidden = false;
    box.textContent = reason?.message || String(reason);
    box.tabIndex=-1; box.focus();
  }
  async function api(path, payload) {
    return request(path, payload === undefined ? undefined : {method:'POST', headers:{'Content-Type':'application/json',
      'X-RCA-CSRF':config.csrf_token}, body:JSON.stringify(payload)});
  }
  function clearTimer() { if (timer) clearTimeout(timer); timer = null; }
  function openWorkspace(showHistory=false) {
    const root=el('investigation-workspace');
    if (root.hidden) return;
    document.querySelector('[data-tab="analysis"]').click();
    if (showHistory) el('investigation-history').open=true;
    else el('workspace-details').open=true;
    const target=showHistory ? el('investigation-history') : el('workspace-details');
    target.scrollIntoView({behavior:'smooth',block:'start'});
    target.querySelector('summary').focus({preventScroll:true});
  }
  function rememberDraft() {
    if (session && !el('investigation-record').hidden) {
      const value=readRecord();
      if (sameRecord(value,session.record)) drafts.delete(session.id);
      else drafts.set(session.id,value);
    }
    while (drafts.size > 20) drafts.delete(drafts.keys().next().value);
  }
  function controls() {
    const busy = session && activeStates.has(session.state);
    const saved = analysis?.workspace_status === 'saved';
    el('open-investigation').hidden=!saved;
    el('start-record').disabled = !saved || busy || Boolean(session);
    el('ask-assistant').disabled = !saved || busy || !config?.assistant_configured || !config?.assistant_profiles.includes(analysis?.profile_id);
    el('cancel-investigation').hidden = !busy;
    el('ask-assistant').textContent = session ? 'Уточнить у помощника' : 'Помощник расследования';
    el('assistant-policy-note').textContent = config?.assistant_configured
      ? 'В OpenAI передаются агрегаты снимка и вопрос. Ручная карточка не передаётся; добавьте в вопрос результаты своих проверок, если они важны для уточнения.'
      : 'Помощник не подключён. Карточка и проверки по наблюдениям доступны.';
    if (config?.assistant_configured) {
      if (config.assistant_budget) el('assistant-policy-note').append(document.createTextNode(
        ` Локальный предел: ${config.assistant_budget.limit_jobs} запусков за скользящие 24 часа; это не расход токенов.`));
      const link=document.createElement('a'); link.href='https://chatgpt.com/settings/usage';
      link.target='_blank'; link.rel='noopener noreferrer'; link.textContent='Расход и лимиты ChatGPT';
      el('assistant-policy-note').append(document.createTextNode(' '),link);
    }
    el('workspace-note').textContent = saved ? 'Результат и наблюдения сохранены локально. Открыть их повторно можно в списке расследований.'
      : analysis ? 'Для этого результата долговременный снимок недоступен. Рейтинг можно сохранить обычным экспортом.'
      : 'Рассчитайте рейтинг для создания новой карточки или откройте сохранённое расследование.';
  }
  function onAnalysis(value) {
    analysis = value;
    if (!restoring) {
      clearDownload();
      rememberDraft(); generation++; clearTimer(); session = null; snapshot = null;
      el('workspace-details').open=false;
      if (el('investigation-record')) {
        el('investigation-record').hidden = true; el('assistant-outcome').hidden = true;
        el('investigation-state').textContent = ''; el('investigation-error').hidden = true;
      }
    }
    if (config) controls();
  }
  function text(value, legend = session?.outcome?.local_identity_legend) {
    return String(value).replace(/\b(?:svc|obs)-\d{3}\b/g, token => {
      if (legend?.services[token]) return legend.services[token];
      const id = legend?.observations[token];
      const fact = snapshot?.catalog.observations.find(f => f.id === id);
      return fact ? `наблюдение ${fact.values.family ? families[fact.values.family] : fact.kind === 'traces' ? 'трассировок' : 'связей'} ${fact.service}` : token;
    });
  }
  function paragraph(parent, value, tag='p') {
    const node = document.createElement(tag); node.textContent = text(value); parent.append(node); return node;
  }
  function list(parent, title, lines) {
    if (!lines?.length) return;
    if (title) paragraph(parent,title,'h4'); const ul = document.createElement('ul');
    lines.forEach(line => paragraph(ul,line,'li')); parent.append(ul);
  }
  function references(parent, ids) {
    for (const id of ids) {
      const fact = snapshot?.catalog.observations.find(f => f.id === id);
      if (!fact) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'evidence-reference';
      button.textContent = `${fact.service} · ${families[fact.values.family] || (fact.kind === 'traces' ? 'трассировки' : 'связи')}`;
      button.addEventListener('click', () => {
        if (state.current?.result_id !== session.analysis_id) return;
        const row = [...document.querySelectorAll('.rank-row')].find(r => r.dataset.service === fact.service);
        if (row) row.click();
        else { const c = state.current?.candidates.find(c => c.service === fact.service); if (c) renderCandidate(c); }
        el('service-detail').scrollIntoView({behavior:'smooth',block:'start'});
      });
      parent.append(button);
    }
  }
  function renderOutcome() {
    el('investigation-state').textContent = session ? labels[session.state] || session.state : '';
    const box = el('assistant-outcome'); box.replaceChildren();
    const outcome = session?.outcome;
    const prior = (session?.turns || []).slice(0,-1);
    box.hidden = !outcome && !prior.length;
    function previousTurns() {
      if (!prior.length) return;
      const details=document.createElement('details'); paragraph(details,`Предыдущие шаги (${prior.length})`,'summary');
      for (const turn of prior) {
        paragraph(details,`Шаг ${turn.number} · ${labels[turn.state] || turn.state}`,'h4');
        paragraph(details,turn.request.question);
        if (turn.outcome?.report) paragraph(details,text(turn.outcome.report.summary,turn.outcome.local_identity_legend));
        else paragraph(details,turn.outcome?.mode==='B' ? 'Детерминированные проверки по сохранённым наблюдениям.' : 'Проверенный ответ не получен.');
      }
      box.append(details);
    }
    if (!outcome) { previousTurns(); return; }
    if (outcome.report) {
      paragraph(box,'Помощник расследования','h3'); paragraph(box,outcome.report.summary);
      for (const h of outcome.report.hypotheses) {
        paragraph(box,h.service,'h4'); paragraph(box,h.statement);
        const support = paragraph(box,'Поддерживающие наблюдения:'); references(support,h.supporting_evidence_ids);
        if (h.contradicting_evidence_ids.length) {
          const contrary = paragraph(box,'Противоречащие наблюдения:'); references(contrary,h.contradicting_evidence_ids);
        }
        if (h.unknowns.length) {
          const unknown=document.createElement('details'); paragraph(unknown,'Что ещё не установлено','summary');
          list(unknown,'',h.unknowns); box.append(unknown);
        }
        for (const check of h.next_checks) {
          paragraph(box,check.action); paragraph(box,`Что должно различить гипотезы: ${check.expected_observation}`);
          references(box,check.evidence_ids);
        }
      }
      const limits=document.createElement('details'); paragraph(limits,'Недостающие данные и ограничения','summary');
      list(limits,'Недостающие данные',outcome.report.data_gaps); list(limits,'Ограничения',outcome.report.limitations); box.append(limits);
      for (const proposal of outcome.report.action_proposals || []) {
        const area=document.createElement('section'); area.className='record-row';
        const purposes={mitigation:'Смягчение последствий',corrective:'Исправление механизма',preventive:'Снижение риска повтора'};
        paragraph(area,`${purposes[proposal.purpose]} · ${proposal.service}`,'h4');
        paragraph(area,text(proposal.title,outcome.local_identity_legend));
        paragraph(area,`Основание: ${text(proposal.rationale,outcome.local_identity_legend)}`);
        paragraph(area,`Как проверить эффект: ${text(proposal.verification_plan,outcome.local_identity_legend)}`);
        references(area,proposal.evidence_ids);
        const adopt=document.createElement('button'); adopt.type='button'; adopt.className='secondary-button';
        adopt.textContent='Добавить в черновик мер';
        const sourceSession=session.id;
        adopt.addEventListener('click',() => {
          if (session?.id!==sourceSession || !record || record.action_items.length>=20) return;
          // Keep unsaved form edits; no server write and no execution here.
          readRecord();
          record.action_items.push(actionFromProposal(proposal,outcome.local_identity_legend));
          renderRows(); dirty(); adopt.disabled=true; adopt.textContent='Добавлено в черновик';
        });
        area.append(adopt); box.append(area);
      }
      if (outcome.consulted_runbooks?.length) {
        const guidance=document.createElement('details');
        paragraph(guidance,'Прочитанные руководства','summary');
        paragraph(guidance,'Рекомендации для проверки, не доказательства причины.');
        for (const ref of outcome.consulted_runbooks) paragraph(guidance,ref.id+' · версия '+ref.version+' · '+ref.section+' · SHA-256 '+ref.sha256);
        box.append(guidance);
      }
    } else if (outcome.mode === 'B' && session.state === 'completed') {
      paragraph(box,'Предложенные проверки','h3');
      const grouped=new Map();
      for (const check of outcome.checks || []) {
        if (!grouped.has(check.service)) grouped.set(check.service,[]);
        grouped.get(check.service).push(check);
      }
      for (const [service,checks] of grouped) {
        const group=document.createElement('details'); paragraph(group,service,'summary');
        const deviations=checks.filter(c => c.code==='CHECK_METRIC_DEVIATION');
        if (deviations.length) {
          const fs=new Set(deviations.flatMap(c => c.evidence_ids).map(id => snapshot.catalog.observations.find(f => f.id===id)?.values.family).filter(Boolean));
          paragraph(group,`Сопоставить с нагрузкой и здоровым периодом: ${[...fs].map(f => families[f] || f).join(', ')}.`);
          references(group,deviations.flatMap(c => c.evidence_ids));
        }
        for (const check of checks.filter(c => c.code!=='CHECK_METRIC_DEVIATION')) { paragraph(group,check.text); references(group,check.evidence_ids); }
        box.append(group);
      }
      if (!outcome.checks?.length) paragraph(box,'Автоматических предложений нет. Проверьте первичные наблюдения и опишите симптомы в карточке.');
    } else {
      paragraph(box,session.state === 'cancelled' ? 'Помощник остановлен. Исходные наблюдения и рейтинг доступны.'
        : session.state === 'interrupted' ? 'Приложение было перезапущено. Задание не повторялось автоматически; при необходимости создайте новый запрос.'
        : 'Проверенный ответ помощника не получен. Используйте наблюдения и детерминированные проверки; диагноз не сформирован.');
      const details = document.createElement('details'); paragraph(details,'Сведения о выполнении','summary');
      paragraph(details,outcome.stop_reason || 'Неизвестная ошибка'); box.append(details);
    }
    if (outcome.usage?.accounting_complete === false) paragraph(box,'Расход последней попытки известен не полностью; отмена не гарантирует прекращения удалённой генерации.');
    if (outcome.usage?.model_calls) {
      const execution=document.createElement('details'); paragraph(execution,'Время и расход','summary');
      if (Number.isFinite(outcome.elapsed_seconds)) paragraph(execution,`Время: ${outcome.elapsed_seconds.toLocaleString('ru-RU',{maximumFractionDigits:1})} с.`);
      paragraph(execution,`Обращений к модели: ${outcome.usage.model_calls}; чтений инструментами: ${outcome.usage.tool_calls || 0}.`);
      paragraph(execution,`Учтено токенов: вход ${outcome.usage.known_input_tokens || 0}, выход ${outcome.usage.known_output_tokens || 0}.`);
      if (outcome.usage.accounting_complete === false) paragraph(execution,'Это известная часть расхода, не полный итог попытки.');
      if (outcome.returned_models?.length) paragraph(execution,`Модель: ${[...new Set(outcome.returned_models)].join(', ')}.`);
      box.append(execution);
    }
    previousTurns();
  }
  function field(row, label, value, onChange, {type='text',options=null,wide=false}={}) {
    const wrapper = document.createElement('label'); if (wide) wrapper.className = 'wide-field';
    wrapper.append(document.createTextNode(label));
    const input = document.createElement(options ? 'select' : type === 'textarea' ? 'textarea' : 'input');
    if (options) for (const [v,t] of options) { const o = document.createElement('option'); o.value=v; o.textContent=t; input.append(o); }
    else if (type !== 'textarea') input.type = type;
    if (type === 'textarea') { input.rows=2; input.maxLength=2000; }
    else if (input.tagName === 'INPUT' && type === 'text') input.maxLength=2000;
    input.value = value ?? ''; input.addEventListener('input',() => { onChange(input.value); dirty(); });
    wrapper.append(input); row.append(wrapper); return input;
  }
  function dirty() {
    el('record-save-state').textContent = 'Есть несохранённые изменения';
    el('record-review-state').textContent = 'Черновик изменён. Предыдущая отметка проверки не подтверждает эти изменения.';
  }
  let record = null;
  function actionFromProposal(proposal, legend) {
    return {id:crypto.randomUUID(),service:proposal.service,purpose:proposal.purpose,
      title:text(proposal.title,legend),rationale:text(proposal.rationale,legend),
      verification_plan:text(proposal.verification_plan,legend),ticket:'',
      owner:'',due_unix:null,status:'proposed',importance:'normal',effort:'unknown',
      verification:'',evidence_ids:[...proposal.evidence_ids]};
  }
  function readRecord() {
    if (!record) return session.record;
    for (const name of ['title','symptoms','impact','conclusion']) record[name] = el('investigation-record').elements[name].value;
    const metadata=Object.fromEntries(['owner','incident','category'].map(name => [name,el('investigation-record').elements[`meta_${name}`].value]));
    if (record.metadata || Object.values(metadata).some(Boolean)) record.metadata=metadata;
    return structuredClone(record);
  }
  function localDate(seconds) {
    if (seconds == null) return '';
    const d = new Date(seconds*1000); return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
  }
  function investigationMarkdown(value, savedSnapshot) {
    // Escape every ASCII punctuation character in untrusted fields: no model
    // HTML, active image/link, heading or fence can become Markdown structure.
    const literal=v => String(v ?? '').replace(/\r\n?/g,'\n')
      .replace(/[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]/g,'\\$&').replace(/\n/g,'  \n');
    const stamp=v => v == null ? 'Не указан' : new Date(v*1000).toISOString();
    const r=value.record, a=savedSnapshot.analysis, lines=['# Расследование инцидента',''];
    const field=(label,v) => lines.push(`${label}: ${literal(v || 'Не указано')}`,'');
    field('Название',r.title); field('Система',value.project); field('ID расследования',value.id);
    field('Редакция',String(value.revision)); field('Начало интервала (UTC)',stamp(a.start_unix));
    field('Конец интервала (UTC)',stamp(a.end_unix));
    field('Состояние карточки',r.approval ? 'Отмечена как проверенная инженером' : 'Черновик, не отмечен как проверенный');
    if (r.approval) field('Время проверки карточки (UTC)',stamp(r.approval.reviewed_at_unix));
    field('Владелец расследования',r.metadata?.owner); field('Исходный инцидент',r.metadata?.incident);
    field('Категория',r.metadata?.category); field('Симптомы',r.symptoms); field('Влияние',r.impact);
    lines.push('## Вывод инженера',''); field('Вывод',r.conclusion);
    lines.push('## Хронология','');
    for (const item of r.timeline) { field('Время (UTC)',stamp(item.time_unix)); field('Событие',item.description); field('Наблюдения',item.evidence_ids.join(', ')); }
    if (!r.timeline.length) lines.push('События не записаны.','');
    lines.push('## Гипотезы и причины','');
    const causeStates={hypothesis:'Гипотеза',confirmed:'Подтверждена инженером',discarded:'Отклонена инженером'};
    for (const item of r.causes) { field('Сервис',item.service); field('Статус',causeStates[item.status]); field('Формулировка',item.statement); field('Основание решения',item.verification); field('Наблюдения',item.evidence_ids.join(', ')); }
    if (!r.causes.length) lines.push('Подтверждённая причина в карточке не записана.','');
    lines.push('## Дальнейшие меры','');
    const purposes={mitigation:'Смягчение последствий',corrective:'Исправление механизма',preventive:'Снижение риска повтора',unspecified:'Не задано'};
    const statuses={proposed:'Предложена',planned:'Запланирована',in_progress:'В работе',verification_pending:'Ожидает проверки',verified:'Эффект проверен',not_verified:'Эффект не подтверждён'};
    const importance={low:'Низкая',normal:'Обычная',high:'Высокая'}, effort={unknown:'Не оценена',small:'Небольшая',medium:'Средняя',large:'Большая'};
    for (const item of r.action_items) {
      field('Мера',item.title); field('Назначение',purposes[item.purpose || 'unspecified']); field('Сервис',item.service);
      field('Основание',item.rationale); field('Ответственный',item.owner); field('Срок (UTC)',stamp(item.due_unix));
      field('Статус',statuses[item.status]); field('Важность',importance[item.importance]); field('Трудоёмкость',effort[item.effort]);
      field('План проверки эффекта',item.verification_plan); field('Фактический результат проверки',item.verification);
      field('Внешний тикет',item.ticket); field('Наблюдения',item.evidence_ids.join(', '));
    }
    if (!r.action_items.length) lines.push('Меры не записаны.','');
    lines.push('## Воспроизводимость и ограничения','');
    field('Версия модели',a.model_version); field('SHA-256 входа',a.input_sha256);
    field('SHA-256 baseline',a.baseline_sha256); field('SHA-256 снимка',savedSnapshot.snapshot_sha256);
    lines.push('Ранг — порядок проверки, не вероятность причины. Отметка проверки карточки не подтверждает автоматически все гипотезы и эффект мер. Приложение не выполняет изменения в наблюдаемых сервисах. Полный снимок и ответы помощника доступны в JSON-экспорте.','');
    return lines.join('\n');
  }
  function epoch(value) { return value ? new Date(value).getTime()/1000 : null; }
  function rowRemove(row, items, item, rerender) {
    const button = document.createElement('button'); button.type='button'; button.className='secondary-button'; button.textContent='Удалить запись';
    button.addEventListener('click',() => { items.splice(items.indexOf(item),1); rerender(); dirty(); }); row.append(button);
  }
  function chooseReferences(row, item) {
    const details=document.createElement('details'); details.className='wide-field';
    const title=document.createElement('summary'); title.textContent=`Связанные наблюдения (${item.evidence_ids.length})`; details.append(title);
    for (const fact of snapshot.catalog.observations) {
      const label=document.createElement('label'), check=document.createElement('input'); check.type='checkbox';
      check.checked=item.evidence_ids.includes(fact.id);
      check.addEventListener('change',() => {
        item.evidence_ids=check.checked ? [...new Set([...item.evidence_ids,fact.id])] : item.evidence_ids.filter(id => id!==fact.id);
        title.textContent=`Связанные наблюдения (${item.evidence_ids.length})`; dirty();
      });
      label.append(check,document.createTextNode(`${fact.service} · ${families[fact.values.family] || (fact.kind==='traces' ? 'трассировки' : 'связи')}`)); details.append(label);
    }
    row.append(details);
  }
  function renderRows() {
    const timeline = el('record-timeline'); timeline.replaceChildren();
    for (const item of record.timeline) {
      const row = document.createElement('div'); row.className='record-row';
      field(row,'Время события',localDate(item.time_unix),v => item.time_unix=epoch(v),{type:'datetime-local'});
      field(row,'Событие',item.description,v => item.description=v,{type:'textarea'});
      chooseReferences(row,item);
      rowRemove(row,record.timeline,item,renderRows); timeline.append(row);
    }
    const causes = el('record-causes'); causes.replaceChildren();
    for (const item of record.causes) {
      const row=document.createElement('div'); row.className='record-row';
      field(row,'Сервис',item.service,v => item.service=v,{options:snapshot.catalog.services.map(s => [s,s])});
      field(row,'Статус',item.status,v => item.status=v,{options:[['hypothesis','Гипотеза'],['confirmed','Подтверждена инженером'],['discarded','Отклонена']]});
      field(row,'Формулировка',item.statement,v => item.statement=v,{type:'textarea'});
      field(row,'Как проверено, основание решения',item.verification,v => item.verification=v,{type:'textarea'});
      chooseReferences(row,item); rowRemove(row,record.causes,item,renderRows); causes.append(row);
    }
    const actions=el('record-actions'); actions.replaceChildren();
    for (const item of record.action_items) {
      const row=document.createElement('div'); row.className='record-row';
      field(row,'Мера',item.title,v => item.title=v,{type:'textarea',wide:true});
      field(row,'Назначение',item.purpose || 'unspecified',v => item.purpose=v,{options:[['unspecified','Не задано'],['mitigation','Смягчение последствий'],['corrective','Исправление механизма'],['preventive','Снижение риска повтора']]});
      field(row,'Ответственный',item.owner,v => item.owner=v);
      field(row,'Срок',localDate(item.due_unix),v => item.due_unix=epoch(v),{type:'datetime-local'});
      const details=document.createElement('details'); details.className='action-details wide-field';
      const verificationStates=new Set(['verification_pending','verified','not_verified']);
      details.open=verificationStates.has(item.status);
      const summary=document.createElement('summary'); summary.textContent='Основание, проверка и дополнительные сведения'; details.append(summary);
      const extra=document.createElement('div'); extra.className='record-grid'; details.append(extra);
      field(row,'Статус',item.status,v => { item.status=v; if (verificationStates.has(v)) details.open=true; },{options:[['proposed','Предложена'],['planned','Запланирована'],['in_progress','В работе'],['verification_pending','Ожидает проверки'],['verified','Эффект проверен'],['not_verified','Эффект не подтверждён']]});
      field(extra,'Основание меры',item.rationale || '',v => item.rationale=v,{type:'textarea',wide:true});
      field(extra,'План проверки эффекта',item.verification_plan || '',v => item.verification_plan=v,{type:'textarea',wide:true});
      field(extra,'Результат проверки эффекта',item.verification,v => item.verification=v,{type:'textarea',wide:true});
      field(extra,'Сервис',item.service || '',v => { if (v) item.service=v; else delete item.service; },{options:[['','Не задан'],...snapshot.catalog.services.map(s => [s,s])]});
      field(extra,'Тикет (номер или ссылка)',item.ticket || '',v => item.ticket=v);
      field(extra,'Важность',item.importance,v => item.importance=v,{options:[['low','Низкая'],['normal','Обычная'],['high','Высокая']]});
      field(extra,'Трудоёмкость',item.effort,v => item.effort=v,{options:[['unknown','Не оценена'],['small','Небольшая'],['medium','Средняя'],['large','Большая']]});
      chooseReferences(extra,item); row.append(details);
      rowRemove(row,record.action_items,item,renderRows); actions.append(row);
    }
  }
  function renderRecord() {
    clearDownload();
    record=structuredClone(drafts.get(session.id) || session.record);
    for (const name of ['title','symptoms','impact','conclusion']) el('investigation-record').elements[name].value=record[name];
    for (const name of ['owner','incident','category']) el('investigation-record').elements[`meta_${name}`].value=record.metadata?.[name] || '';
    el('investigation-record').hidden=false; el('record-save-state').textContent=drafts.has(session.id) ? 'Черновик не сохранён' : '';
    el('record-review-state').textContent=drafts.has(session.id)
      ? 'Есть несохранённый черновик; прежняя отметка проверки не относится к изменениям.'
      : record.approval
      ? `Карточка проверена инженером ${new Date(record.approval.reviewed_at_unix*1000).toLocaleString('ru-RU')}. Это не подтверждает все гипотезы или эффект всех мер.`
      : 'Карточка не отмечена как проверенная инженером.';
    renderRows();
  }
  async function poll(id, version) {
    try {
      const value=await api(`/api/v2/investigations/${encodeURIComponent(id)}`);
      if (version !== generation || session?.id !== id) return;
      session=value.revision<session.revision ? {...value,record:session.record,revision:session.revision} : value;
      renderOutcome(); controls();
      if (activeStates.has(value.state)) timer=setTimeout(() => poll(id,version),1000);
      else await history();
    } catch (reason) { if (version===generation) message(reason); }
  }
  async function choose(value) {
    rememberDraft(); clearTimer(); generation++;
    const version=generation;
    const loaded=await api(`/api/v2/analyses/${encodeURIComponent(value.analysis_id)}/snapshot`);
    if (version!==generation) return;
    snapshot=loaded;
    restoring=true;
    try {
      renderRanking(snapshot.analysis);
      if ([...el('profile-select').options].some(o => o.value===snapshot.analysis.profile_id)) el('profile-select').value=snapshot.analysis.profile_id;
      function localSeconds(seconds) { const d=new Date(seconds*1000); return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19); }
      el('start-time').value=localSeconds(snapshot.analysis.start_unix); el('end-time').value=localSeconds(snapshot.analysis.end_unix);
    } finally { restoring=false; }
    resetError();
    el('request-status').textContent='Открыто сохранённое расследование. Источники заново не запрашивались.';
    session=value; el('investigation-question').value=value.request.question;
    renderOutcome(); renderRecord(); controls();
    openWorkspace();
    if (activeStates.has(value.state)) poll(value.id,generation);
  }
  let historyGeneration=0;
  async function history() {
    const list=el('investigation-list');
    const version=++historyGeneration, query=new URLSearchParams();
    for (const key of ['project','service','category','action_status']) {
      const value=el(`history-${key}`).value.trim(); if (value) query.set(key,value);
    }
    for (const key of ['after','before']) {
      const value=el(`history-${key}`).value; if (value) query.set(key,String(epoch(value)));
    }
    query.set('limit','100');
    const data=await api('/api/v2/investigations?'+query);
    if (version!==historyGeneration) return;
    list.replaceChildren();
    if (!data.investigations.length) paragraph(list,'Нет расследований, соответствующих фильтрам.');
    else paragraph(list,`Показано ${data.investigations.length}, максимум ${data.limit}. Период — дата создания карточки.`);
    for (const item of data.investigations) {
      const button=document.createElement('button'); button.type='button'; button.className='workspace-history-item';
      button.textContent=`${item.title || item.project} · ${labels[item.state] || item.state} · ${new Date(item.created*1000).toLocaleString('ru-RU')}`;
      button.addEventListener('click',async () => { const version=generation; try { const value=await api(`/api/v2/investigations/${item.id}`); if (version===generation) await choose(value); } catch (reason) { message(reason); } }); list.append(button);
      if (item.mentioned_services?.length) paragraph(list,`Записаны инженером: ${item.mentioned_services.join(', ')}. Подтверждены: ${item.confirmed_services.join(', ') || 'нет'}.`);
      if (item.action_count) paragraph(list,`Мер: ${item.action_count}; просрочены и открыты: ${item.overdue_action_count}.`);
      const remove=document.createElement('button'); remove.type='button'; remove.className='secondary-button'; remove.textContent='Удалить снимок и связанные карточки';
      remove.addEventListener('click',async () => {
        if (!window.confirm('Удалить этот снимок и все связанные расследования из приложения? Восстановление не предусмотрено. Выгруженные файлы и данные в источниках останутся.')) return;
        try {
          await api(`/api/v2/analyses/${item.analysis_id}/delete`,{});
          if (session?.analysis_id===item.analysis_id) clearResult();
          await history();
        } catch (reason) { message(reason); }
      }); list.append(remove);
    }
  }
  async function start(mode) {
    const selected=analysis?.result_id, version=generation;
    if (!selected) return;
    try {
      el('investigation-error').hidden=true; el('start-record').disabled=true; el('ask-assistant').disabled=true;
      const input={mode,question:el('investigation-question').value.trim() || 'Какие гипотезы проверить и каких данных не хватает?',idempotency_key:crypto.randomUUID()};
      const value=session && mode==='D'
        ? await api(`/api/v2/investigations/${session.id}/messages`,input)
        : await api('/api/v2/investigations',{analysis_id:selected,...input});
      if (version===generation && analysis?.result_id===selected) await choose(value);
      await history();
    } catch (reason) { message(reason); } finally { controls(); }
  }
  async function init() {
    try { config=await request('/api/v2/workspace'); } catch { return; }
    el('investigation-workspace').hidden=false; analysis=state.current; controls();
    el('history-shortcut').hidden=false;
    el('history-shortcut').addEventListener('click',() => openWorkspace(true));
    el('open-investigation').addEventListener('click',() => openWorkspace());
    el('start-record').addEventListener('click',() => start('B'));
    el('ask-assistant').addEventListener('click',() => start('D'));
    el('cancel-investigation').addEventListener('click',async () => { try { session=await api(`/api/v2/investigations/${session.id}/cancel`,{}); renderOutcome(); controls(); } catch (e) { message(e); } });
    el('investigation-record').addEventListener('input',event => { clearDownload(); if (event.target.id!=='export-format') dirty(); });
    el('history-apply').addEventListener('click',() => history().catch(message));
    el('history-reset').addEventListener('click',() => {
      for (const key of ['project','service','category','action_status','after','before']) el(`history-${key}`).value='';
      history().catch(message);
    });
    el('add-timeline').addEventListener('click',() => { if (record.timeline.length>=50) return; record.timeline.push({time_unix:analysis.start_unix,description:'',evidence_ids:[]}); renderRows(); dirty(); });
    el('add-cause').addEventListener('click',() => { if (record.causes.length>=10) return; record.causes.push({service:snapshot.catalog.services[0],statement:'',status:'hypothesis',verification:'',evidence_ids:[]}); renderRows(); dirty(); });
    el('add-action').addEventListener('click',() => { if (record.action_items.length>=20) return; record.action_items.push({id:crypto.randomUUID(),title:'',owner:'',due_unix:null,status:'proposed',importance:'normal',effort:'unknown',verification:'',evidence_ids:[]}); renderRows(); dirty(); });
    el('investigation-record').addEventListener('submit',async event => {
      event.preventDefault();
      el('investigation-error').hidden=true;
      const identifier=session.id, version=generation;
      try {
        const saved=await api(`/api/v2/investigations/${identifier}/record`,{expected_revision:session.revision,record:readRecord()});
        drafts.delete(identifier);
        if (version===generation && session?.id===identifier) { session=saved; renderRecord(); el('record-save-state').textContent='Сохранено'; }
        await history();
      }
      catch (reason) { message(reason); }
    });
    el('review-record').addEventListener('click',async () => {
      try {
        if (!sameRecord(readRecord(),session.record)) throw new Error('Перед проверкой сохраните изменения карточки.');
        const identifier=session.id, version=generation;
        const saved=await api(`/api/v2/investigations/${identifier}/review`,{expected_revision:session.revision});
        if (version===generation && session?.id===identifier) { session=saved; renderRecord(); }
      } catch (reason) { message(reason); }
    });
    el('export-investigation').addEventListener('click',exportInvestigation);
    await history();
  }
  window.RCAWorkspace={onAnalysis};
  document.addEventListener('DOMContentLoaded',init);
})();
