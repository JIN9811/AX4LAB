import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

const $ = (id) => document.getElementById(id);
const canvas = $('scene');
const viewport = canvas.parentElement;
let model, k, gap, playing = false, clock = 0, animationHigh = .45, last = performance.now();
let showLabels = true;
const groups = {}, objects = [];

async function init() {
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true, preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = new RoomEnvironment();
  scene.environment = pmrem.fromScene(env, .04).texture;
  env.dispose();pmrem.dispose();
  const camera = new THREE.PerspectiveCamera(36, 1, .01, 30);
  camera.up.set(0,0,1);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = .10;
  controls.minDistance = .18;controls.maxDistance = 8;
  controls.maxPolarAngle = Math.PI*.51;
  scene.add(new THREE.HemisphereLight(0xf5faff,0x778879,.9));
  const key = new THREE.DirectionalLight(0xfffbef,2.0);
  key.position.set(1.8,-2.6,4.5);key.castShadow=true;
  key.shadow.mapSize.set(2048,2048);
  Object.assign(key.shadow.camera,{left:-2,right:2,top:2.5,bottom:-2,near:.1,far:10});
  key.shadow.bias=-.0003;key.shadow.normalBias=.003;scene.add(key);
  const fill=new THREE.DirectionalLight(0xd9e9ff,1.3);fill.position.set(-2,1,3);scene.add(fill);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(10,10),new THREE.ShadowMaterial({color:0x728379,opacity:.20}));
  ground.position.z=-.001;ground.receiveShadow=true;scene.add(ground);
  const grid = new THREE.GridHelper(5,50,0xc4d2c8,0xe1e7e2);grid.rotation.x=Math.PI/2;grid.position.z=-.0015;scene.add(grid);

  const response = await fetch('./scene.json.gz');
  if (!response.ok) throw new Error(`모델 파일 로드 실패 (${response.status})`);
  const decoded=response.body.pipeThrough(new DecompressionStream('gzip'));
  model = await new Response(decoded).json();k=model.kinematics;gap=k.default_gap;
  const dims=model.provenance.dimensions;
  $('bodyDimensions').textContent=['body_width','body_depth','body_height'].map(name=>dims[name].value.toLocaleString('en-US')).join(' × ');
  $('deckSurfaceHeight').textContent=dims.deck_height.value;
  $('platenDimensions').textContent=`하부 Ø${dims.platen_diameter.value} × ${dims.platen_thickness.value} / 상부 Ø${dims.upper_platen_diameter.value} × ${dims.upper_platen_thickness.value} mm`;
  $('previewRange').textContent=`${k.min_gap*1000}–${k.max_gap*1000}`;
  const margin=(dims.body_depth.value-dims.column_depth.value)/2, offset=dims.frame_y_offset.value;
  $('frameDepthDimensions').textContent=[margin+offset,dims.column_depth.value,margin-offset].map(mm=>mm/10).join(' / ');
  const columnWidth=(dims.frame_width.value-dims.column_clearance.value)/2;
  $('frameWidthDimensions').textContent=[columnWidth,dims.column_clearance.value,columnWidth].join(' / ');
  const loader=new THREE.TextureLoader();
  const textures = {};
  await Promise.all([...new Set(model.parts.filter(p=>p.texture).map(p=>p.texture))].map(async path=>{
    const tex=await loader.loadAsync(path);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=renderer.capabilities.getMaxAnisotropy();textures[path]=tex;
  }));
  for (const [name, tf] of Object.entries(model.groups)) {
    const g=new THREE.Group();g.name=name;g.position.fromArray(tf.translation);g.scale.fromArray(tf.scale);scene.add(g);groups[name]=g;
  }
  for (const p of model.parts) {
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(p.vertices,3));geometry.setIndex(p.indices);
    if(p.normals)geometry.setAttribute('normal',new THREE.Float32BufferAttribute(p.normals,3));else geometry.computeVertexNormals();
    if(p.uv) geometry.setAttribute('uv',new THREE.Float32BufferAttribute(p.uv,2));
    const material=new THREE.MeshStandardMaterial({color:p.color,metalness:p.metallic,roughness:p.roughness,side:THREE.DoubleSide,map:p.texture?textures[p.texture]:null,
      flatShading:p.category==='Bellows'||p.name.includes('Beam')||p.name.includes('Column')||p.name.includes('Cabinet')||p.name.includes('Case')});
    const mesh=new THREE.Mesh(geometry,material);mesh.name=p.name;mesh.userData={category:p.category,group:p.group};mesh.castShadow=!p.texture;mesh.receiveShadow=true;groups[p.group].add(mesh);objects.push(mesh);
    if(/^(Upper|Lower)Ring/.test(p.name)){material.color.set('#737b83');material.polygonOffset=true;material.polygonOffsetFactor=-2;material.polygonOffsetUnits=-2;mesh.castShadow=false;}
  }
  // Line measures the actual contact gap, not crosshead translation from an arbitrary zero.
  const dimension = new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x2a856a,depthTest:false,transparent:true,opacity:.85}));dimension.renderOrder=10;scene.add(dimension);
  const contactZ=k.lower_surface_z, frameY=k.frame_y_offset ?? 0;
  function setGap(mm,manual=false,preserveInput=false) {
    if(!Number.isFinite(mm)){ $('gapInput').value=(gap*1000).toFixed(1);return; }
    gap=THREE.MathUtils.clamp(mm/1000,k.min_gap,k.max_gap);
    if(manual) stop();
    groups.Crosshead.position.z=contactZ+gap;
    const bottom=contactZ+gap+k.upper_stack, top=bottom+k.crosshead_thickness;
    for (const side of ['Left','Right']) {
      groups['BellowsLower'+side].position.z=k.deck_height;
      groups['BellowsLower'+side].scale.z=bottom-k.deck_height;
      groups['BellowsUpper'+side].position.z=top;
      groups['BellowsUpper'+side].scale.z=k.top_under-top;
    }
    if(!preserveInput)$('gapInput').value=(gap*1000).toFixed(1);$('gapSlider').value=gap*1000;
    $('upperReadout').textContent=((contactZ+gap)*1000).toFixed(1)+' mm';
    $('lowerReadout').textContent=(contactZ*1000).toFixed(1)+' mm';
    $('crossheadReadout').textContent=(top*1000).toFixed(1)+' mm';
    $('gapLabel').textContent=`간격 ${(gap*1000).toFixed(1)} mm`;
    const x=.108,y=frameY-.026,z=contactZ,z1=z+gap;
    dimension.geometry.setAttribute('position',new THREE.Float32BufferAttribute([x,y,z,x,y,z1,x-.009,y,z,x+.009,y,z,x-.009,y,z1,x+.009,y,z1],3));
    dimension.geometry.computeBoundingSphere();
  }
  function stop(){playing=false;$('play').setAttribute('aria-pressed','false');$('playText').textContent='움직임 재생';$('playIcon').textContent='▷';}
  function cameraView(view) {
    const portrait=viewport.clientWidth/viewport.clientHeight < .8;
    const distance=portrait?1.25:1;
    if(view==='emergency') {
      const x=(dims.frame_width.value+dims.column_clearance.value)/4000;
      const y=frameY-dims.column_depth.value/2000;
      const z=dims.deck_height.value/1000+.16;
      controls.target.set(x,y-.02,z);camera.position.set(x+.16,y-.26,z+.12);
    } else if(view==='indicator') {
      const dims=model.provenance.dimensions;
      const x=(dims.frame_width.value/2+dims.indicator_column_clearance.value+dims.indicator_width.value/2)/1000;
      const z=dims.indicator_center_height.value/1000;
      const mountY=frameY+(dims.indicator_mount_y_offset?.value??70)/1000;
      controls.target.set(x-.045,mountY-.025,z-.025);camera.position.set(x+.48,mountY+.58,z+.24);
    } else if(view==='work') {
      const center=contactZ+Math.min(gap,.45)/2+.050;
      controls.target.set(0,frameY,center);camera.position.set(.46,frameY-.68,center+.32);
    } else {
      controls.target.set(.025,0,.96);
      if(view==='front')camera.position.set(.025,-3.55*distance,1.03);
      else if(view==='rear')camera.position.set(-1.7*distance,3.35*distance,1.95);
      else if(view==='side')camera.position.set(3.6*distance,.0,1.03);
      else camera.position.set(2.25*distance,-3.1*distance,2.05);
    }
    camera.lookAt(controls.target);controls.update();
    document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  }
  function resize(){const w=viewport.clientWidth,h=viewport.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
  new ResizeObserver(resize).observe(viewport);resize();cameraView('iso');
  function placeLabel(element,position) {
    const p=position.clone().project(camera);
    element.style.left=((p.x+1)*.5*viewport.clientWidth)+'px';element.style.top=((-p.y+1)*.5*viewport.clientHeight)+'px';
    element.style.display=showLabels && p.z>-1 && p.z<1 && Math.abs(p.x)<.96 && Math.abs(p.y)<.96 ? 'block':'none';
  }
  $('gapInput').min=$('gapSlider').min=k.min_gap*1000;$('gapInput').max=$('gapSlider').max=k.max_gap*1000;
  $('maxGapLabel').textContent=(k.max_gap*1000)+' mm';
  $('gapSlider').addEventListener('input',e=>setGap(Number(e.target.value),true));
  $('gapInput').addEventListener('focus',stop);
  $('gapInput').addEventListener('input',e=>{if(e.target.value.trim()!=='')setGap(Number(e.target.value),true,true);});
  $('gapInput').addEventListener('change',e=>setGap(e.target.value.trim()===''?NaN:Number(e.target.value),true));
  $('gapInput').addEventListener('blur',e=>setGap(e.target.value.trim()===''?NaN:Number(e.target.value),true));
  document.querySelectorAll('[data-gap]').forEach(b=>b.addEventListener('click',()=>setGap(Number(b.dataset.gap),true)));
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>cameraView(b.dataset.view)));
  const period=model.provenance.preview.animation_seconds;
  $('play').addEventListener('click',()=>{if(playing){stop();return;}animationHigh=Math.min(k.max_gap,Math.max(model.provenance.preview.animation_max_gap_mm/1000,gap));clock=Math.acos(THREE.MathUtils.clamp(1-2*(gap-k.min_gap)/(animationHigh-k.min_gap),-1,1))*period/(2*Math.PI);playing=true;$('play').setAttribute('aria-pressed','true');$('playText').textContent='일시정지';$('playIcon').textContent='Ⅱ';});
  $('highlight').addEventListener('change',e=>{objects.filter(o=>o.userData.group==='Crosshead').forEach(o=>{o.material.emissive.set(e.target.checked?0x0b5b43:0);o.material.emissiveIntensity=e.target.checked?.4:0;});});
  $('showFrame').addEventListener('change',e=>{objects.filter(o=>['Frame','Cabinet','Bellows','Indicator'].includes(o.userData.category)).forEach(o=>{o.visible=e.target.checked;});});
  $('showLabels').addEventListener('change',e=>{showLabels=e.target.checked;dimension.visible=showLabels;});
  setGap(gap*1000);
  $('modelStatus').textContent=`${model.parts.length}개 부품 · 수직 1축 · 모델 미리보기`;
  $('loading').style.display='none';document.body.dataset.ready='true';
  // Calibrated preview input in millimetres. Never sends commands to equipment.
  window.qm100tModel = Object.freeze({
    limits: Object.freeze({min:k.min_gap*1000, max:k.max_gap*1000}),
    setGapMm(mm) {
      if (!Number.isFinite(mm) || mm < k.min_gap*1000 || mm > k.max_gap*1000) return false;
      setGap(mm, true);
      return true;
    },
    getGapMm: () => gap*1000,
  });
  window.dispatchEvent(new Event('qm100t:model-ready'));
  function render(now) {
    const dt=Math.min((now-last)/1000,.1);last=now;
    if(playing){clock+=dt;const low=k.min_gap;setGap((low+(animationHigh-low)*(.5-.5*Math.cos(clock*2*Math.PI/period)))*1000);}
    controls.update();
    placeLabel($('gapLabel'),new THREE.Vector3(.108,frameY-.026,contactZ+gap/2));
    placeLabel($('fixedLabel'),new THREE.Vector3(-.095,frameY,contactZ-.035));
    renderer.render(scene,camera);requestAnimationFrame(render);
  }
  requestAnimationFrame(render);
}
init().catch(error=>{console.error(error);$('loading').innerHTML='';const msg=document.createElement('div');msg.className='error';msg.textContent='모델을 열지 못했습니다: '+error.message+' · 페이지를 새로고침해 주세요.';$('loading').appendChild(msg);});
