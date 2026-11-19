# HandToDigital

تطبيق ويب يحوّل صفحات PDF المكتوبة بخط اليد إلى صفحات دفتر رقمية باستخدام نموذج رؤية من Google Gemini أو OpenAI.

## آلية العمل
1. يقرأ المتصفح ملف PDF ويعرض صفحاته بالترتيب باستخدام PDF.js.
2. يحوّل كل صفحة إلى صورة ويرسلها إلى FastAPI.
3. يرسل الخادم صورة الصفحة إلى مزود الذكاء الاصطناعي، ويستقبل HTML مؤقتاً.
4. يعيد HTML إلى المتصفح، حيث يحوّل إلى PNG باستخدام html2canvas.
5. يجمع المتصفح الصور بالترتيب في ملف PDF نهائي باستخدام pdf-lib.

## التشغيل المحلي
يتطلب Python 3.11 أو أحدث.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

افتح http://127.0.0.1:8000

## إعداد النماذج
- Gemini: مثال `gemini-2.5-flash`.
- OpenAI: مثال `gpt-4.1-mini` (يجب أن يدعم الصور).
اسم النموذج يجب أن يكون متاحاً لمفتاح API المستخدم. التكلفة تخص حساب صاحب المفتاح.

## واجهات التشغيل والمراقبة
- `GET /api/health`: فحص صحة التطبيق، مناسب لاستخدامه كـ ALB Target Group health check.
- `GET /api/instance-info`: يعرض Instance ID وAvailability Zone وPrivate IP عند التشغيل على EC2.
- استجابة `POST /api/convert-page` تتضمن `instance_info` للخادم الذي عالج الصفحة.
- تُقرأ بيانات EC2 باستخدام IMDSv2 فقط. عند التشغيل محلياً، تكون `available=false`.
- جميع استجابات `/api/*` تحمل ترويسات تمنع التخزين المؤقت.

## النشر على Ubuntu EC2
يوفر مجلد `deploy/` ملفات إعداد Nginx وsystemd وسكربت تثبيت أولي.

1. أنشئ EC2 Ubuntu 24.04 LTS مع صلاحية خروج إلى الإنترنت عبر NAT Gateway عند وضعه في Private Subnet.
2. فعّل IMDSv2 (HttpTokens=required) في إعدادات Metadata Options.
3. اتصل بالخادم عبر Session Manager أو وسيلة إدارة آمنة، ثم انسخ المستودع وشغّل سكربت التثبيت:
   ```bash
   sudo git clone https://github.com/7m4/HandToDigital.git /opt/handtodigital
   sudo bash /opt/handtodigital/deploy/install.sh
   ```
4. يثبت السكربت Python وNginx والاعتماديات، ويجهز خدمة systemd وموقع Nginx.
5. تحقق محلياً على الخادم من `http://127.0.0.1/api/health`، ثم اربط ALB بالمنفذ 80 في Security Group الخاص بالخادم.

**ملاحظة Golden AMI:** شغّل التثبيت والتحقق على Instance تأسيسية، ثم أنشئ AMI مخصصة منها. عند إطلاق Instances من هذه AMI يجب أن تعمل خدمة `handtodigital` تلقائياً. لا تُضمّن API Keys أو ملفات مستخدمين في AMI.

## الخصوصية والأمان
- ملف PDF الأصلي لا يُرفع إلى خادم التطبيق؛ المتصفح يرسل صورة كل صفحة إلى الخادم.
- مفتاح API يُرسل إلى الخادم في طلب المعالجة ولا يُحفظ في قاعدة بيانات أو ملف.
- لا يخزن التطبيق ملفات PDF أو HTML أو الصور على الخادم.
- لا تسجل أجسام الطلبات أو ترويسات Authorization/API Key في سجلات Nginx أو التطبيق.
- استخدم HTTPS عبر CloudFront/ALB، واجعل EC2 في Private Subnets ولا تسمح بالوصول المباشر من الإنترنت.
- اسمح بالوصول إلى IMDS عبر IMDSv2 فقط، ولا تعطّل حماية SSRF.
- احتفظ بتخزين CloudFront المؤقت معطلاً لمسارات `/api/*`، خصوصاً معلومات الخادم والطلبات الديناميكية.
- الاحتفاظ بالملف الأصلي يعني إبقاء نسخة المصدر في جهاز المستخدم. خيار عدم الاحتفاظ يزيل مرجع الملف من واجهة التطبيق بعد نجاح التحويل؛ لا يستطيع الموقع حذف ملف من قرص المستخدم.

## ملاحظات
- إخراج الصفحات بمقاس A4 وبنفس ترتيب المصدر.
- الحد الافتراضي في الواجهة 40MB و60 صفحة.
- قد يخطئ النموذج في قراءة الخط اليدوي؛ راجع الناتج قبل الاعتماد عليه.
- تتم معالجة كل صفحة منفردة؛ الوقت والتكلفة يعتمدان على عدد الصفحات والنموذج.
