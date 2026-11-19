(() => {
  const $ = id => document.getElementById(id);
  const form = $("convertForm"), fileInput = $("pdfFile"), dropzone = $("dropzone");
  const startBtn = $("startBtn"), progressPanel = $("progressPanel"), progressBar = $("progressBar");
  const pageList = $("pageList"), errorBox = $("errorBox");
  let selectedFile = null, finalPdfBytes = null, finalFileName = "HandToDigital-result.pdf";
  pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

  $("provider").addEventListener("change", () => {
    $("model").value = $("provider").value === "gemini" ? "gemini-3.8-flash" : "gpt-4.1-mini";
  });
  $("toggleKey").addEventListener("click", () => {
    const el = $("apiKey"); el.type = el.type === "password" ? "text" : "password";
  });
  function errorMessage(value) {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
      if (typeof value.message === "string") return value.message;
      if (typeof value.detail === "string") return value.detail;
      if (Array.isArray(value)) return value.map(errorMessage).filter(Boolean).join("، ");
      try { return JSON.stringify(value); } catch (_) {}
    }
    return "حدث خطأ غير معروف.";
  }
  function showError(msg) { errorBox.textContent = errorMessage(msg); errorBox.classList.remove("hidden"); }
  function hideError() { errorBox.textContent = ""; errorBox.classList.add("hidden"); }
  function setFile(file) {
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) return showError("يرجى اختيار ملف PDF صالح.");
    if (file.size > 40 * 1024 * 1024) return showError("حجم الملف يتجاوز الحد المسموح (40 MB).");
    selectedFile = file; $("fileTitle").textContent = file.name;
    $("fileSub").textContent = (file.size / 1024 / 1024).toFixed(2) + " MB"; hideError();
  }
  fileInput.addEventListener("change", e => setFile(e.target.files[0]));
  ["dragenter","dragover"].forEach(n => dropzone.addEventListener(n,e=>{e.preventDefault();dropzone.classList.add("dragover");}));
  ["dragleave","drop"].forEach(n => dropzone.addEventListener(n,e=>{e.preventDefault();dropzone.classList.remove("dragover");}));
  dropzone.addEventListener("drop",e=>setFile(e.dataTransfer.files[0]));

  function showInstanceInfo(info) {
    if (!info || !info.available) {
      $("instanceId").textContent = "غير متاح";
      $("instanceAz").textContent = "—";
      $("instanceIp").textContent = "—";
      $("instanceNote").textContent = (info && info.message) || "تعذر الحصول على بيانات EC2. تأكد أن التطبيق يعمل على EC2 وأن IMDSv2 مفعّل.";
      return;
    }
    $("instanceId").textContent = info.instance_id || "—";
    $("instanceAz").textContent = info.availability_zone || "—";
    $("instanceIp").textContent = info.private_ip || "—";
    $("instanceNote").textContent = "هذه معلومات الـ EC2 Instance الذي استجاب لطلب معلومات الخادم.";
  }

  async function loadCurrentInstanceInfo() {
    try {
      const response = await fetch("/api/instance-info", { cache: "no-store" });
      if (!response.ok) {
        showInstanceInfo({available:false,message:"تعذر جلب معلومات Instance (HTTP " + response.status + ")."});
        return;
      }
      showInstanceInfo(await response.json());
    } catch (_) {
      showInstanceInfo({available:false,message:"تعذر الاتصال بخدمة معلومات Instance."});
    }
  }
  loadCurrentInstanceInfo();

  function updateProgress(done,total,label) {
    const pct = total ? Math.round(done/total*100) : 0;
    progressBar.style.width = pct+"%"; $("pageCounter").textContent = done+" / "+total+" صفحة";
    $("percent").textContent = pct+"%"; if(label) $("progressText").textContent=label;
  }
  function addPageItem(n) {
    const item=document.createElement("div"); item.className="page-item";
    const name=document.createElement("span"), status=document.createElement("span");
    name.textContent="الصفحة "+n; status.className="status"; status.textContent="بانتظار المعالجة";
    item.append(name,status); pageList.appendChild(item); return item;
  }
  function setPageStatus(item,label,state) { item.querySelector(".status").textContent=label; item.className="page-item "+(state||""); }
  const toDataUrl = blob => new Promise((resolve,reject)=>{
    const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=reject; reader.readAsDataURL(blob);
  });
  async function renderPdfPage(pdf,n) {
    const page=await pdf.getPage(n), base=page.getViewport({scale:1});
    const viewport=page.getViewport({scale:Math.min(2,1800/base.width)});
    const canvas=document.createElement("canvas"); canvas.width=Math.ceil(viewport.width); canvas.height=Math.ceil(viewport.height);
    const ctx=canvas.getContext("2d",{alpha:false}); ctx.fillStyle="#fff"; ctx.fillRect(0,0,canvas.width,canvas.height);
    await page.render({canvasContext:ctx,viewport}).promise;
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",0.88));
    canvas.width=0; canvas.height=0; if(!blob) throw new Error("تعذر تجهيز صورة الصفحة "+n);
    return toDataUrl(blob);
  }
  async function htmlToPng(html) {
    const frame=document.createElement("iframe");
    frame.setAttribute("sandbox","allow-same-origin");
    frame.style.cssText="position:fixed;left:-10000px;top:0;width:794px;height:1123px;border:0;background:white";
    document.body.appendChild(frame);
    try {
      const doc=frame.contentDocument; doc.open(); doc.write(html); doc.close();
      await new Promise(resolve=>setTimeout(resolve,500));
      await doc.fonts.ready.catch(()=>{});
      const target=doc.querySelector(".page")||doc.body;
      const canvas=await html2canvas(target,{backgroundColor:"#fff",scale:2,useCORS:false,logging:false,width:794,windowWidth:794,height:Math.max(1123,target.scrollHeight),windowHeight:Math.max(1123,target.scrollHeight)});
      return await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error("فشل تحويل HTML إلى صورة.")),"image/png"));
    } finally { frame.remove(); }
  }
  async function makeOutputPdf(blobs) {
    const out=await PDFLib.PDFDocument.create(), w=595.28,h=841.89;
    for(const blob of blobs) {
      const img=await out.embedPng(await blob.arrayBuffer()), page=out.addPage([w,h]);
      const scale=Math.min(w/img.width,h/img.height), iw=img.width*scale, ih=img.height*scale;
      page.drawImage(img,{x:(w-iw)/2,y:(h-ih)/2,width:iw,height:ih});
    }
    return out.save();
  }
  $("downloadBtn").addEventListener("click",()=>{
    if(!finalPdfBytes)return; const url=URL.createObjectURL(new Blob([finalPdfBytes],{type:"application/pdf"}));
    const a=document.createElement("a"); a.href=url; a.download=finalFileName; a.click(); setTimeout(()=>URL.revokeObjectURL(url),30000);
  });

  form.addEventListener("submit",async e=>{
    e.preventDefault(); hideError();
    if(!selectedFile)return showError("يرجى اختيار ملف PDF أولاً.");
    const apiKey=$("apiKey").value.trim(), model=$("model").value.trim();
    if(!apiKey||!model)return showError("أدخل API Key واسم النموذج.");
    startBtn.disabled=true; $("resultActions").classList.add("hidden"); progressPanel.classList.remove("hidden"); pageList.innerHTML=""; finalPdfBytes=null;
    try {
      $("progressText").textContent="جارٍ قراءة ملف PDF...";
      const pdf=await pdfjsLib.getDocument({data:new Uint8Array(await selectedFile.arrayBuffer())}).promise;
      if(pdf.numPages>60)throw new Error("الحد الأقصى هو 60 صفحة في الملف الواحد.");
      if(!pdf.numPages)throw new Error("ملف PDF لا يحتوي على صفحات.");
      const items=Array.from({length:pdf.numPages},(_,i)=>addPageItem(i+1)), images=[];
      updateProgress(0,pdf.numPages,"جارٍ تحويل الصفحات بالترتيب...");
      for(let n=1;n<=pdf.numPages;n++) {
        const item=items[n-1];
        try {
          setPageStatus(item,"جارٍ تجهيز الصورة","");
          const image=await renderPdfPage(pdf,n);
          setPageStatus(item,"جارٍ تحليل الكتابة","");
          const response=await fetch("/api/convert-page",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
            provider:$("provider").value,api_key:apiKey,model,image_data_url:image,page_number:n,
            extra_instructions:$("instructions").value.trim()
          })});
          let data;
          try { data = await response.json(); }
          catch (_) { throw new Error("استجابة الخادم ليست JSON صالحة (HTTP " + response.status + ")."); }
          if(!response.ok) throw new Error(errorMessage(data.detail || data.error || data.message || data));
          showInstanceInfo(data.instance_info);
          setPageStatus(item,"جارٍ إنشاء الصورة","");
          images.push(await htmlToPng(data.html)); setPageStatus(item,"اكتملت","done");
          updateProgress(n,pdf.numPages,"تمت معالجة "+n+" من "+pdf.numPages+" صفحة");
        } catch(err) { setPageStatus(item,"فشلت","error"); throw new Error("الصفحة "+n+": "+(err.message||"حدث خطأ غير معروف")); }
      }
      $("progressText").textContent="جارٍ تجميع الصور في ملف PDF النهائي...";
      finalPdfBytes=await makeOutputPdf(images);
      finalFileName=selectedFile.name.replace(/\.pdf$/i,"")+"-digital.pdf";
      updateProgress(pdf.numPages,pdf.numPages,"اكتمل التحويل بنجاح");
      $("resultInfo").textContent=$("retention").value==="yes"
        ?"تم تجهيز الملف. الملف الأصلي بقي على جهازك ولم يُرفع إلى خادم التطبيق."
        :"تم تجهيز الملف. لم يتم حفظ نسخة من الملف الأصلي على خادم التطبيق.";
      $("resultActions").classList.remove("hidden");
      if($("retention").value==="no") {
        selectedFile=null; fileInput.value=""; $("fileTitle").textContent="اسحب ملف PDF إلى هنا"; $("fileSub").textContent="أو اضغط لاختيار الملف من جهازك";
      }
      images.length=0;
    } catch(err) { showError(err.message||"حدث خطأ أثناء التحويل."); $("progressText").textContent="توقفت عملية التحويل."; }
    finally { startBtn.disabled=false; }
  });
})();