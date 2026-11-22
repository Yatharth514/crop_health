import React, {useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
const API=(import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000').replace(/\/$/,'');
const labels={healthy:'Healthy',early_blight:'Early Blight',late_blight:'Late Blight'};

const SENSOR_DEVICE_ID='wokwi-esp32-01';

async function fetchSensorJson(url,signal){
 const response=await fetch(url,{signal});
 let data;
 try{data=await response.json()}catch{throw new Error('The server returned an unreadable response.')} 
 if(!response.ok)throw new Error(data.detail||`Sensor request failed (${response.status}).`);
 return data;
}

function formatSensorTime(value){
 if(!value)return 'Not received yet';
 const date=new Date(value);
 return Number.isNaN(date.getTime())?'Timestamp unavailable':date.toLocaleString();
}

function sensorValue(value,digits=1){
 return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'—';
}

function SensorChart({title,values,unit,color}){
 if(!values.length)return <div className="sensor-chart-empty">No history available yet.</div>;
 const width=640,height=190,left=28,right=12,top=14,bottom=30;
 const low=Math.min(...values),high=Math.max(...values),span=high-low||1;
 const points=values.map((value,index)=>{
  const x=values.length===1?(left+width-right)/2:left+(index/(values.length-1))*(width-left-right);
  const y=top+((high-value)/span)*(height-top-bottom);
  return {x,y,value};
 });
 return <div className="sensor-chart-wrap"><svg className="sensor-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} history, ${values.length} readings`}>
  <title>{title} history</title>
  {[0,1,2].map(row=>{const y=top+row*((height-top-bottom)/2);return <line key={row} x1={left} x2={width-right} y1={y} y2={y} className="sensor-chart-grid"/>})}
  <text x="2" y={top+4} className="sensor-chart-label">{high.toFixed(1)}{unit}</text>
  <text x="2" y={height-bottom+4} className="sensor-chart-label">{low.toFixed(1)}{unit}</text>
  {points.length>1&&<polyline points={points.map(point=>`${point.x},${point.y}`).join(' ')} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>}
  {points.map((point,index)=><circle key={index} cx={point.x} cy={point.y} r="4" fill={color}><title>{`${point.value.toFixed(1)}${unit}`}</title></circle>)}
  <text x={left} y={height-5} className="sensor-chart-label">Oldest</text>
  <text x={width-right} y={height-5} textAnchor="end" className="sensor-chart-label">Newest</text>
 </svg></div>;
}

function SensorDashboard({apiBase}){
 const [sensorData,setSensorData]=useState({latest:null,history:null,alerts:null,status:null});
 const [sensorErrors,setSensorErrors]=useState({});
 const [sensorLoading,setSensorLoading]=useState(true);
 const [sensorRefreshing,setSensorRefreshing]=useState(false);
 const [sensorUpdatedAt,setSensorUpdatedAt]=useState(null);
 const refreshRef=useRef(null);

 useEffect(()=>{
  let mounted=true,inFlight=false,controller=null;
  const deviceQuery=`device_id=${encodeURIComponent(SENSOR_DEVICE_ID)}`;
  const endpoints={
   latest:`${apiBase}/api/sensors/latest?${deviceQuery}`,
   history:`${apiBase}/api/sensors/history?${deviceQuery}`,
   alerts:`${apiBase}/api/sensors/alerts?${deviceQuery}&active_only=true`,
   status:`${apiBase}/api/sensors/status?${deviceQuery}`
  };
  const refresh=async()=>{
   if(!mounted||inFlight)return;
   inFlight=true;
   controller=new AbortController();
   setSensorRefreshing(true);
   const results=await Promise.allSettled(Object.entries(endpoints).map(async([key,url])=>[key,await fetchSensorJson(url,controller.signal)]));
   if(mounted){
    let successCount=0;
    const failures={};
    const successes={};
    for(const result of results){
     if(result.status==='fulfilled'){
      const [key,value]=result.value;
      successes[key]=value;
      successCount++;
     }else if(result.reason?.name!=='AbortError'){
      const endpoint=Object.keys(endpoints)[results.indexOf(result)];
      failures[endpoint]=result.reason?.message||'Sensor information could not be loaded.';
     }
    }
    if(successCount){
     setSensorData(current=>({...current,...successes}));
     setSensorUpdatedAt(new Date());
    }
    setSensorErrors(current=>{
     const next={...current,...failures};
     for(const key of Object.keys(successes))delete next[key];
     return next;
    });
    setSensorLoading(false);
    setSensorRefreshing(false);
   }
   inFlight=false;
  };
  refreshRef.current=refresh;
  void refresh();
  const timer=window.setInterval(()=>void refresh(),5000);
  return()=>{
   mounted=false;
   window.clearInterval(timer);
   controller?.abort();
   refreshRef.current=null;
  };
 },[apiBase]);

 const latestItem=sensorData.latest?.items?.find(item=>item?.device_id===SENSOR_DEVICE_ID);
 const statusItem=sensorData.status?.items?.find(item=>item?.device_id===SENSOR_DEVICE_ID);
 const statusReading=statusItem?.latest_reading;
 const statusHasMetrics=statusReading&&typeof statusReading==='object'&&['temperature_c','humidity_percent','gas_reading'].some(key=>statusReading[key]!==undefined&&statusReading[key]!==null);
 const latestCandidate=statusHasMetrics?statusReading:latestItem?.latest_reading;
 const latestReading=latestCandidate&&typeof latestCandidate==='object'&&Object.keys(latestCandidate).length?latestCandidate:null;
 const activeAlerts=Array.isArray(statusItem?.active_alerts)?statusItem.active_alerts:
  (Array.isArray(sensorData.alerts?.items)?sensorData.alerts.items.filter(alert=>!alert?.cleared_at):[]);
 const historyItems=Array.isArray(sensorData.history?.items)?[...sensorData.history.items].reverse():[];
 const hasReceivedData=Boolean(latestReading);
 const anySensorEndpointSucceeded=Object.values(sensorData).some(Boolean);
 const latestWasChecked=Boolean(sensorData.latest||sensorData.status);
 const riskLevel=!hasReceivedData?'UNAVAILABLE':activeAlerts.length===0?'NORMAL':activeAlerts.length===1?'WARNING':'CRITICAL';
 const lastReceived=statusItem?.last_received_at||latestReading?.received_at||null;
 const firstError=Object.values(sensorErrors)[0];
 const displayUnavailable=(key)=>sensorLoading?'Loading…':sensorErrors[key]&&!sensorData[key]?'Unavailable':'—';

 return <section className="sensor-dashboard" aria-labelledby="sensor-dashboard-title" aria-busy={sensorRefreshing}>
  <div className="sensor-dashboard-heading">
   <div><span className="sensor-kicker">ENVIRONMENTAL MONITORING</span><h2 id="sensor-dashboard-title">Field conditions</h2><p>Live readings and alert history from the sensor node.</p></div>
   <button className="sensor-refresh" type="button" onClick={()=>refreshRef.current?.()} disabled={sensorRefreshing}>
    <span aria-hidden="true">↻</span>{sensorRefreshing?'Refreshing…':'Refresh'}
   </button>
  </div>

  <div className="sensor-device-bar">
   <div><span className="sensor-device-label">DEVICE</span><strong>{SENSOR_DEVICE_ID}</strong></div>
   <div><span className="sensor-device-label">LAST RECEIVED</span><strong>{lastReceived?formatSensorTime(lastReceived):sensorLoading?'Loading…':latestWasChecked?'No reading received yet':'Unavailable'}</strong></div>
   <div className={`sensor-risk sensor-risk-${riskLevel.toLowerCase()}`}><span className="sensor-device-label">ENVIRONMENTAL RISK</span><strong>{riskLevel}</strong></div>
  </div>

  {firstError&&<p className="sensor-error" role="status">Some monitoring data could not be refreshed. {firstError}{sensorUpdatedAt&&<span> Showing the latest available data from {formatSensorTime(sensorUpdatedAt)}.</span>}</p>}

  <div className="sensor-metrics">
   <article className="sensor-metric-card"><span className="sensor-metric-icon sensor-icon-temperature" aria-hidden="true">°</span><span className="sensor-metric-name">Temperature</span><strong>{latestReading?sensorValue(latestReading.temperature_c):displayUnavailable('latest')}<small>°C</small></strong><span className="sensor-metric-foot">Air temperature</span></article>
   <article className="sensor-metric-card"><span className="sensor-metric-icon sensor-icon-humidity" aria-hidden="true">◌</span><span className="sensor-metric-name">Humidity</span><strong>{latestReading?sensorValue(latestReading.humidity_percent):displayUnavailable('latest')}<small>%</small></strong><span className="sensor-metric-foot">Relative humidity</span></article>
   <article className="sensor-metric-card"><span className="sensor-metric-icon sensor-icon-gas" aria-hidden="true">⌁</span><span className="sensor-metric-name">Simulated gas reading</span><strong>{latestReading?sensorValue(latestReading.gas_reading,0):displayUnavailable('latest')}<small>ADC proxy</small></strong><span className="sensor-metric-foot">Range 0–4095 · proxy, not concentration</span></article>
  </div>

  <div className="sensor-lower-grid">
   <section className="sensor-card sensor-history-card" aria-labelledby="sensor-history-title">
    <div className="sensor-card-heading"><div><span className="sensor-kicker">RECENT READINGS</span><h3 id="sensor-history-title">Environmental history</h3></div><span className="sensor-history-count">{sensorData.history?.total??'—'} samples</span></div>
    {sensorErrors.history&&!sensorData.history?<p className="sensor-inline-state" role="status">History unavailable: {sensorErrors.history}</p>:sensorLoading&&!sensorData.history?<p className="sensor-inline-state" role="status">Loading history…</p>:!historyItems.length?<p className="sensor-inline-state">No historical readings available yet.</p>:<div className="sensor-charts">
     <SensorChart title="Temperature" values={historyItems.map(item=>item?.temperature_c).filter(value=>typeof value==='number'&&Number.isFinite(value))} unit="°C" color="#b5794d"/>
     <SensorChart title="Humidity" values={historyItems.map(item=>item?.humidity_percent).filter(value=>typeof value==='number'&&Number.isFinite(value))} unit="%" color="#668b76"/>
     <SensorChart title="Simulated gas reading" values={historyItems.map(item=>item?.gas_reading).filter(value=>typeof value==='number'&&Number.isFinite(value))} unit="" color="#71865e"/>
    </div>}
   </section>

   <section className="sensor-card sensor-alert-card" aria-labelledby="sensor-alert-title">
    <div className="sensor-card-heading"><div><span className="sensor-kicker">THRESHOLD EVENTS</span><h3 id="sensor-alert-title">Active alerts</h3></div><span className="sensor-alert-count">{activeAlerts.length}</span></div>
    {sensorErrors.status&&!sensorData.status&&sensorErrors.alerts&&!sensorData.alerts?<p className="sensor-inline-state sensor-inline-error" role="status">Alerts unavailable. {sensorErrors.status}</p>:sensorLoading&&!sensorData.status&&!sensorData.alerts?<p className="sensor-inline-state" role="status">Loading alerts…</p>:activeAlerts.length===0?<div className="sensor-no-alerts"><span aria-hidden="true">✓</span><strong>No active alerts</strong><p>All reported environmental metrics are within their alert state.</p></div>:<ul className="sensor-alert-list">{activeAlerts.map(alert=><li className="sensor-alert-item" key={alert.id||`${alert.metric}-${alert.triggered_at}`}><span className="sensor-alert-dot" aria-hidden="true"/><div><strong>{alert.metric==='gas_proxy'?'Simulated gas':alert.metric==='temperature'?'Temperature':alert.metric==='humidity'?'Humidity':alert.metric||'Sensor metric'} threshold exceeded</strong><span>{sensorValue(alert.observed_value)} observed · threshold {sensorValue(alert.threshold)} · {formatSensorTime(alert.triggered_at)}</span></div><em>{alert.severity||'warning'}</em></li>)}</ul>}
   </section>
  </div>
  <div className="sensor-dashboard-foot">{sensorUpdatedAt?`Data refreshed ${formatSensorTime(sensorUpdatedAt)}`:sensorLoading?'Connecting to sensor service…':!anySensorEndpointSucceeded?'Sensor service unavailable':''}</div>
 </section>;
}

function App(){
 const input=useRef(null),[file,setFile]=useState(null),[preview,setPreview]=useState(''),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[drag,setDrag]=useState(false),[modelInfo,setModelInfo]=useState(null),[modelLoading,setModelLoading]=useState(true),[modelError,setModelError]=useState('');
 useEffect(()=>{if(!file){setPreview('');return}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url)},[file]);
 useEffect(()=>{const controller=new AbortController();async function loadModelInfo(){setModelLoading(true);setModelError('');try{const response=await fetch(`${API}/api/model-info`,{signal:controller.signal});let data;try{data=await response.json()}catch{throw new Error('The server returned an unreadable model-information response.')}if(!response.ok)throw new Error(data.detail||'Model information could not be loaded.');setModelInfo(data)}catch(e){if(e.name!=='AbortError'){setModelInfo(null);setModelError(e instanceof TypeError?'Cannot reach the model information service. Check that the FastAPI backend is running.':e.message||'Model information could not be loaded.')}}finally{if(!controller.signal.aborted)setModelLoading(false)}}loadModelInfo();return()=>controller.abort()},[]);
 function select(f){if(!f)return;if(!['image/jpeg','image/png','image/webp'].includes(f.type)){setError('Choose a JPEG, PNG, or WebP image.');return}if(f.size>10*1024*1024){setError('Image must be 10 MB or smaller.');return}setError('');setResult(null);setFile(f);}
 async function analyze(){if(!file)return;setBusy(true);setError('');try{const body=new FormData();body.append('image',file);const r=await fetch(`${API}/api/predict`,{method:'POST',body});let data;try{data=await r.json()}catch{throw new Error('The server returned an unreadable response.')}if(!r.ok)throw new Error(data.detail||'Prediction request failed.');setResult(data)}catch(e){setError(e instanceof TypeError?'Cannot reach the prediction service. Start the FastAPI backend and try again.':e.message||'Prediction failed.')}finally{setBusy(false)}}
 function reset(){if(preview)URL.revokeObjectURL(preview);setFile(null);setPreview('');setResult(null);setError('');if(input.current)input.current.value=''}
 return <main className="page"><header><a className="brand" href="#top"><span className="brand-icon">✳</span><span>FIELDNOTE <i>AI</i></span></a><span className="badge"><b></b> TOMATO LEAF ANALYSIS</span></header><section className="hero" id="top"><div className="eyebrow"><span></span> CROP HEALTH EARLY WARNING NODE</div><h1>See the signs.<br/><em>Know what to look for.</em></h1><p className="intro">Upload a tomato leaf photo for a quick AI classification across healthy, early blight, and late blight.</p></section>
 <section className="model-panel" aria-labelledby="model-heading"><div className="model-heading"><div><span className="step">MODEL</span><h2 id="model-heading">Classification model</h2></div>{!modelLoading&&!modelError&&<span className={`model-status ${modelInfo?.model_available?'available':'unavailable'}`}><b></b>{modelInfo?.model_available?'MODEL AVAILABLE':'MODEL UNAVAILABLE'}</span>}</div>{modelLoading?<p className="model-message" role="status"><span className="spinner dark-spinner"/>Loading model information…</p>:modelError?<div className="model-message model-error" role="alert"><span>{modelError}</span><button className="retry" onClick={()=>{setModelLoading(true);setModelError('');const controller=new AbortController();fetch(`${API}/api/model-info`,{signal:controller.signal}).then(async response=>{let data;try{data=await response.json()}catch{throw new Error('The server returned an unreadable model-information response.')}if(!response.ok)throw new Error(data.detail||'Model information could not be loaded.');setModelInfo(data)}).catch(e=>{setModelInfo(null);setModelError(e instanceof TypeError?'Cannot reach the model information service. Check that the FastAPI backend is running.':e.message||'Model information could not be loaded.')}).finally(()=>setModelLoading(false))}}>Try again</button></div>:<><div className="model-grid"><div><span>ARCHITECTURE</span><strong>{modelInfo?.architecture||'Unavailable'}</strong></div><div><span>SUPPORTED CLASSES</span><strong>{modelInfo?.supported_classes?.length?modelInfo.supported_classes.map(name=>labels[name]||name).join(' · '):'Unavailable'}</strong></div><div><span>FEATURE COUNT</span><strong>{modelInfo?.feature_count??'Unavailable'}</strong></div><div><span>HYPERPARAMETERS</span><strong>{modelInfo?.parameters?Object.entries(modelInfo.parameters).map(([key,value])=>`${key}: ${value===null?'none':value}`).join(' · '):'Unavailable'}</strong></div></div>{!modelInfo?.model_available&&<p className="unavailable-note" role="status">The model service is currently unavailable. Image predictions will not run until it is ready.</p>}</>}</section>
 <section className="workspace"><div className="panel"><div className="panel-title"><div><span className="step">01</span><h2>Choose a leaf image</h2></div><span className="file-hint">JPG, PNG, WEBP · UP TO 10 MB</span></div>
 {!preview?<div className={`dropzone ${drag?'drag':''}`} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);select(e.dataTransfer.files[0])}} onClick={()=>input.current?.click()} role="button" tabIndex="0" aria-label="Choose a tomato leaf image. JPEG, PNG, or WebP, up to 10 megabytes." onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.current?.click()}}}><div className="upload-icon" aria-hidden="true">↑</div><strong>Drop your image here</strong><span>or <u>browse files</u> from your device</span><input ref={input} type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Choose image file" onChange={e=>{select(e.target.files[0]);e.target.value=''}}/></div>:<div className="preview"><img src={preview} alt="Selected tomato leaf"/><button className="change" onClick={()=>input.current?.click()}>Change image</button><input ref={input} type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Choose a different image" onChange={e=>{select(e.target.files[0]);e.target.value=''}}/></div>}
 {error&&<div className="error" role="alert">{error}</div>}<button className="analyze" disabled={!file||busy||modelInfo?.model_available===false} onClick={analyze} aria-live="polite">{busy?<><span className="spinner"/>Analyzing leaf…</>:'Analyze Leaf'}<span aria-hidden="true">↗</span></button><div className="secure">⌁ <span>Your image is processed for this prediction only.</span></div></div>
 <div className="panel results"><div className="panel-title"><div><span className="step">02</span><h2>Analysis</h2></div><span className="live"><b></b> MODEL OUTPUT</span></div>{!preview&&!result?<div className="empty"><div className="leaf-mark">✳</div><strong>Your result will appear here</strong><span>Choose an image to begin the analysis.</span></div>:!result?<div className="empty image-wait"><img src={preview} alt="Preview of selected leaf"/><strong>Ready to analyze</strong><span>Run the model to see its classification scores.</span></div>:<div className="result-content"><div className="result-photo"><img src={preview} alt="Analyzed tomato leaf"/><span>YOUR IMAGE</span></div><div className="prediction"><small>TOP CLASSIFICATION</small><h3>{labels[result.predicted_class]||result.predicted_class}</h3><span className="score">{(result.top_prediction_score*100).toFixed(1)}% <i>top model score</i></span></div><div className="scores"><div className="score-head"><strong>Class scores</strong><span>MODEL SCORES · NOT PROBABILITIES</span></div>{['healthy','early_blight','late_blight'].map(key=><div className="score-row" key={key}><div><span>{labels[key]}</span><b>{((result.class_scores?.[key]||0)*100).toFixed(1)}%</b></div><div className="track"><span style={{width:`${Math.max(0,Math.min(100,(result.class_scores?.[key]||0)*100))}%`}}/></div></div>)}</div><p className="score-note">{result.score_note||'Scores are model outputs and are not calibrated probabilities.'}</p><button className="again" onClick={reset}>Analyze another image <span>↗</span></button></div>}</div></section>
 <SensorDashboard apiBase={API}/>
 <footer><p><b>Prototype notice</b> · Trained on PlantVillage images. Results are not a definitive plant disease diagnosis.</p><span>CROP HEALTH AI <i>·</i> IMAGE CLASSIFICATION</span></footer></main>
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);
