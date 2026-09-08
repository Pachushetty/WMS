/**
 * EcoCycle AI — Enterprise Scanner & Inference Console Logic
 * Handles drag & drop, sample preset loading, laser scan animation,
 * API communication with /predict, and real-time probability visualization.
 */

document.addEventListener('DOMContentLoaded', () => {
  const uploadBox = document.getElementById('uploadBox');
  const fileInput = document.getElementById('fileInput');
  const browseBtn = document.getElementById('browseBtn');
  const cameraInput = document.getElementById('cameraInput');
  const cameraBtn = document.getElementById('cameraBtn');
  const previewCard = document.getElementById('previewCard');
  const previewImage = document.getElementById('previewImage');
  const previewFileName = document.getElementById('previewFileName');
  const previewFileSize = document.getElementById('previewFileSize');
  const clearImageBtn = document.getElementById('clearImageBtn');
  const analyzeBtn = document.getElementById('analyzeBtn');
  const analyzeBtnText = document.getElementById('analyzeBtnText');
  const statusMessage = document.getElementById('statusMessage');
  const scanLaser = document.getElementById('scanLaser');

  // State sections
  const idleState = document.getElementById('idleState');
  const loadingState = document.getElementById('loadingState');
  const resultsDashboard = document.getElementById('resultsDashboard');
  const unclearResultBanner = document.getElementById('unclearResultBanner');
  const confidentResultSection = document.getElementById('confidentResultSection');

  // Presets
  const presetButtons = document.querySelectorAll('.btn-preset');
  const copyReportBtn = document.getElementById('copyReportBtn');
  const copyReportBtnText = document.getElementById('copyReportBtnText');

  let selectedFile = null;
  let lastPredictionData = null;

  // --- 1. File Upload & Drag-and-Drop ---
  if (browseBtn && fileInput) {
    browseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  if (cameraInput) {
    cameraInput.addEventListener('change', () => {
      if (cameraInput.files.length > 0) {
        handleFileSelection(cameraInput.files[0]);
      }
    });
  }

  // --- 1b. Live Camera Capture (getUserMedia modal) ---
  // Uses the browser MediaDevices API to show a live preview and lets the
  // user capture a frame. The captured frame is converted to a File and
  // routed through the exact same handleFileSelection() function used by
  // Browse Files / drag & drop, so it flows into the existing preview +
  // /predict analysis pipeline with zero duplicate logic.
  (function initCameraCapture() {
    const overlay = document.getElementById('cameraModalOverlay');
    if (!cameraBtn || !overlay) return;

    const modalBody = document.getElementById('cameraModalBody');
    const video = document.getElementById('cameraLiveVideo');
    const canvas = document.getElementById('cameraCapturedCanvas');
    const loadingOverlay = document.getElementById('cameraLoadingOverlay');
    const errorOverlay = document.getElementById('cameraErrorOverlay');
    const errorTitle = document.getElementById('cameraErrorTitle');
    const errorDesc = document.getElementById('cameraErrorDesc');
    const closeBtn = document.getElementById('cameraModalCloseBtn');
    const cancelBtn = document.getElementById('cameraCancelBtn');
    const cancelBtnText = document.getElementById('cameraCancelBtnText');
    const captureBtn = document.getElementById('cameraCaptureBtn');
    const retakeBtn = document.getElementById('cameraRetakeBtn');
    const usePhotoBtn = document.getElementById('cameraUsePhotoBtn');

    let activeStream = null;

    function stopStream() {
      if (activeStream) {
        activeStream.getTracks().forEach(track => track.stop());
        activeStream = null;
      }
      if (video) {
        video.pause();
        video.srcObject = null;
      }
    }

    function resetModalUI() {
      if (modalBody) modalBody.classList.remove('has-capture');
      if (loadingOverlay) loadingOverlay.classList.remove('is-visible');
      if (errorOverlay) errorOverlay.classList.remove('is-visible');
      if (captureBtn) captureBtn.style.display = 'none';
      if (retakeBtn) retakeBtn.style.display = 'none';
      if (usePhotoBtn) usePhotoBtn.style.display = 'none';
      if (cancelBtnText) cancelBtnText.textContent = 'Cancel';
    }

    function closeModal() {
      stopStream();
      overlay.classList.remove('is-open');
      document.body.style.overflow = '';
      resetModalUI();
    }

    function showError(title, desc) {
      if (loadingOverlay) loadingOverlay.classList.remove('is-visible');
      if (errorTitle) errorTitle.textContent = title;
      if (errorDesc) errorDesc.textContent = desc;
      if (errorOverlay) errorOverlay.classList.add('is-visible');
      if (captureBtn) captureBtn.style.display = 'none';
      if (retakeBtn) retakeBtn.style.display = 'none';
      if (usePhotoBtn) usePhotoBtn.style.display = 'none';
      if (cancelBtnText) cancelBtnText.textContent = 'Close';
    }

    async function openModal() {
      // Feature detection: fall back to the native file-input camera
      // capture (cameraInput, capture="environment") on unsupported browsers.
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        if (cameraInput) {
          cameraInput.click();
        } else {
          showStatusAlert('Camera capture is not supported in this browser.', 'error');
        }
        return;
      }

      resetModalUI();
      overlay.classList.add('is-open');
      document.body.style.overflow = 'hidden';
      if (loadingOverlay) loadingOverlay.classList.add('is-visible');

      try {
        activeStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1280 },
            height: { ideal: 960 }
          },
          audio: false
        });

        if (video) {
          video.srcObject = activeStream;
          await video.play().catch(() => {});
        }

        if (loadingOverlay) loadingOverlay.classList.remove('is-visible');
        if (captureBtn) captureBtn.style.display = 'inline-flex';
      } catch (err) {
        stopStream();
        let title = 'Camera unavailable';
        let desc = 'We couldn\'t access your camera. You can still upload a photo using Browse Files.';

        if (err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')) {
          title = 'Camera permission denied';
          desc = 'Please allow camera access in your browser settings, then try again.';
        } else if (err && (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError')) {
          title = 'No camera found';
          desc = 'We couldn\'t detect a camera on this device. Try Browse Files instead.';
        } else if (err && (err.name === 'NotReadableError' || err.name === 'TrackStartError')) {
          title = 'Camera in use';
          desc = 'Your camera may be in use by another application. Close it and try again.';
        }

        showError(title, desc);
      }
    }

    function capturePhoto() {
      if (!video || !canvas || !activeStream) return;

      const width = video.videoWidth || 1280;
      const height = video.videoHeight || 960;
      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, width, height);

      if (modalBody) modalBody.classList.add('has-capture');
      if (captureBtn) captureBtn.style.display = 'none';
      if (retakeBtn) retakeBtn.style.display = 'inline-flex';
      if (usePhotoBtn) usePhotoBtn.style.display = 'inline-flex';

      // Pause the live feed while previewing the captured frame; the
      // underlying tracks stay open in case the user chooses Retake.
      video.pause();
    }

    function retakePhoto() {
      if (modalBody) modalBody.classList.remove('has-capture');
      if (captureBtn) captureBtn.style.display = 'inline-flex';
      if (retakeBtn) retakeBtn.style.display = 'none';
      if (usePhotoBtn) usePhotoBtn.style.display = 'none';
      if (video) video.play().catch(() => {});
    }

    function usePhoto() {
      canvas.toBlob((blob) => {
        if (!blob) {
          showStatusAlert('Could not process the captured photo. Please try again.', 'error');
          return;
        }
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const file = new File([blob], `camera-capture-${timestamp}.jpg`, { type: 'image/jpeg' });

        // Route the captured frame through the EXACT same pipeline used
        // for Browse Files / drag & drop uploads (preview + /predict).
        handleFileSelection(file);

        closeModal();
      }, 'image/jpeg', 0.92);
    }

    cameraBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openModal();
    });

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (captureBtn) captureBtn.addEventListener('click', capturePhoto);
    if (retakeBtn) retakeBtn.addEventListener('click', retakePhoto);
    if (usePhotoBtn) usePhotoBtn.addEventListener('click', usePhoto);

    // Click outside the panel closes the modal (and releases the camera).
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    // Escape key closes the modal.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('is-open')) {
        closeModal();
      }
    });

    // Safety net: release the camera if the user navigates away.
    window.addEventListener('beforeunload', stopStream);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && overlay.classList.contains('is-open') && !modalBody.classList.contains('has-capture')) {
        // Keep the stream alive on simple tab switches; only hard-stop on unload.
      }
    });
  })();

  if (uploadBox && fileInput) {
    uploadBox.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(evt => {
      uploadBox.addEventListener(evt, (e) => {
        e.preventDefault();
        uploadBox.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(evt => {
      uploadBox.addEventListener(evt, (e) => {
        e.preventDefault();
        uploadBox.classList.remove('dragover');
      });
    });

    uploadBox.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileSelection(files[0]);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        handleFileSelection(fileInput.files[0]);
      }
    });
  }

  if (clearImageBtn) {
    clearImageBtn.addEventListener('click', () => {
      resetUploadState();
    });
  }

  function formatBytes(bytes, decimals = 1) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }

  function handleFileSelection(file) {
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg'];
    if (!validTypes.includes(file.type)) {
      showStatusAlert('Unsupported file format. Please upload a PNG or JPEG image.', 'error');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      showStatusAlert('File size exceeds the 10MB limit.', 'error');
      return;
    }

    selectedFile = file;
    clearStatusAlert();

    const reader = new FileReader();
    reader.onload = (e) => {
      previewImage.src = e.target.result;
      previewFileName.textContent = file.name;
      previewFileSize.textContent = formatBytes(file.size);

      uploadBox.style.display = 'none';
      previewCard.style.display = 'block';
      analyzeBtn.disabled = false;

      // Reset dashboard to idle if a new file is uploaded
      showIdleState();
    };
    reader.readAsDataURL(file);
  }

  function resetUploadState() {
    selectedFile = null;
    if (fileInput) fileInput.value = '';
    if (cameraInput) cameraInput.value = '';
    if (previewImage) previewImage.src = '';
    if (uploadBox) uploadBox.style.display = 'block';
    if (previewCard) previewCard.style.display = 'none';
    if (analyzeBtn) analyzeBtn.disabled = true;
    clearStatusAlert();
    showIdleState();
  }

  function showStatusAlert(msg, type = 'info') {
    if (!statusMessage) return;
    statusMessage.innerHTML = `
      <div class="alert-banner alert-${type === 'error' ? 'error' : 'warning'}" style="padding: 10px 14px; margin-bottom: 0;">
        <span>${msg}</span>
      </div>
    `;
  }

  function clearStatusAlert() {
    if (statusMessage) statusMessage.innerHTML = '';
  }

  // --- 2. Synthetic Sample Presets for One-Click Evaluation ---
  presetButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const presetType = btn.getAttribute('data-preset');
      loadPresetSpecimen(presetType);
    });
  });

  function loadPresetSpecimen(presetType) {
    // Each preset has no real bundled photo, so we synthesize a clearly-
    // labeled placeholder image client-side and feed it through the exact
    // same handleFileSelection() -> /predict pipeline as a real upload.
    // Styling below intentionally stays muted/neutral (small icon, single
    // dark title, one small colored tag) to match the rest of the app's
    // flat, professional card language instead of a bright poster look.
    const PRESETS = {
      battery:     { filename: 'lithium_aa_battery.jpg', icon: '🔋', title: 'Used AA Battery', tag: 'Hazardous Waste', tagColor: '#EF4444' },
      banana:      { filename: 'organic_banana_peel.jpg', icon: '🍌', title: 'Discarded Banana Peel', tag: 'Organic Waste', tagColor: '#10B981' },
      bottle:      { filename: 'pet_plastic_bottle.jpg', icon: '🧴', title: 'Crushed Plastic Bottle', tag: 'Recyclable Waste', tagColor: '#2563EB' },
      fresh_apple: { filename: 'fresh_apple.jpg', icon: '🍎', title: 'Fresh Red Apple', tag: 'Not Waste', tagColor: '#94A3B8' },
      new_bottle:  { filename: 'new_plastic_bottle.jpg', icon: '🧴', title: 'New Sealed Bottle', tag: 'Not Waste', tagColor: '#94A3B8' },
      living_pet:  { filename: 'living_pet_dog.jpg', icon: '🐕', title: 'Golden Retriever Dog', tag: 'Not Waste', tagColor: '#94A3B8' },
    };
    const preset = PRESETS[presetType];
    if (!preset) return;

    const canvas = document.createElement('canvas');
    canvas.width = 400;
    canvas.height = 400;
    const ctx = canvas.getContext('2d');

    // Neutral card background with a subtle grid, matching the app's
    // existing "empty state" panels rather than a saturated illustration.
    ctx.fillStyle = '#F8FAFC';
    ctx.fillRect(0, 0, 400, 400);
    ctx.strokeStyle = '#E2E8F0';
    ctx.lineWidth = 1;
    for (let i = 0; i < 400; i += 40) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 400); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(400, i); ctx.stroke();
    }

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Small circular chip behind the icon, sized modestly (not a huge emoji).
    ctx.fillStyle = '#FFFFFF';
    ctx.beginPath();
    ctx.arc(200, 165, 48, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#E2E8F0';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.font = '48px sans-serif';
    ctx.fillText(preset.icon, 200, 168);

    // Single, consistent dark title (no per-preset loud colors).
    ctx.fillStyle = '#0F172A';
    ctx.font = 'bold 19px "Plus Jakarta Sans", sans-serif';
    ctx.fillText(preset.title, 200, 245);

    // One small muted category tag, styled like the site's real badges.
    ctx.font = '600 12px "Plus Jakarta Sans", sans-serif';
    const tagText = preset.tag.toUpperCase();
    const tagWidth = ctx.measureText(tagText).width + 28;
    const tagX = 200 - tagWidth / 2;
    const tagY = 268;
    ctx.fillStyle = preset.tagColor + '1A'; // ~10% opacity fill
    ctx.beginPath();
    ctx.roundRect(tagX, tagY, tagWidth, 26, 13);
    ctx.fill();
    ctx.fillStyle = preset.tagColor;
    ctx.fillText(tagText, 200, tagY + 13);

    ctx.fillStyle = '#94A3B8';
    ctx.font = '11px "JetBrains Mono", monospace';
    ctx.fillText('Demo test specimen — no upload required', 200, 320);

    canvas.toBlob((blob) => {
      const file = new File([blob], preset.filename, { type: 'image/jpeg' });
      handleFileSelection(file);
    }, 'image/jpeg', 0.95);
  }

  // --- 3. Viewport State Controllers ---
  function showIdleState() {
    if (idleState) idleState.style.display = 'flex';
    if (loadingState) loadingState.style.display = 'none';
    if (resultsDashboard) resultsDashboard.style.display = 'none';
    if (scanLaser) scanLaser.style.display = 'none';
  }

  function showLoadingState() {
    if (idleState) idleState.style.display = 'none';
    if (loadingState) loadingState.style.display = 'flex';
    if (resultsDashboard) resultsDashboard.style.display = 'none';
    if (scanLaser) scanLaser.style.display = 'block';
  }

  function showResultsState() {
    if (idleState) idleState.style.display = 'none';
    if (loadingState) loadingState.style.display = 'none';
    if (resultsDashboard) resultsDashboard.style.display = 'block';
    if (scanLaser) scanLaser.style.display = 'none';
  }

  // --- 4. API Request and Model Inference ---
  if (analyzeBtn) {
    analyzeBtn.addEventListener('click', async () => {
      if (!selectedFile) return;

      analyzeBtn.disabled = true;
      analyzeBtnText.textContent = 'Executing Neural Inference...';
      clearStatusAlert();
      showLoadingState();

      const formData = new FormData();
      formData.append('image', selectedFile);

      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

      try {
        const response = await fetch('/predict', {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
          body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
          showStatusAlert(data.error || 'Prediction service error encountered.', 'error');
          showIdleState();
          return;
        }

        lastPredictionData = data;
        renderInferenceResults(data);
      } catch (err) {
        showStatusAlert('Could not communicate with the neural prediction backend.', 'error');
        showIdleState();
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtnText.textContent = 'Analyze Waste Specimen';
      }
    });
  }

  // ==========================================================================
  // Actionable Disposal Protocol Mapping & Resolution Engine
  // Resolves item-specific instructions: DETECTED ITEM -> PROTOCOL
  // ==========================================================================
  function getDisposalProtocol(itemOrData, optionalCategory, optionalIsWaste) {
    let detectedItem = '';
    let category = optionalCategory || '';
    let isWaste = optionalIsWaste !== undefined ? optionalIsWaste : true;

    if (typeof itemOrData === 'object' && itemOrData !== null) {
      if (itemOrData.protocol && itemOrData.protocol.warning && Array.isArray(itemOrData.protocol.instructions) && itemOrData.protocol.instructions.length > 0) {
        return {
          warning: itemOrData.protocol.warning,
          steps: itemOrData.protocol.instructions,
        };
      }
      if (itemOrData.guidance && itemOrData.guidance.summary && Array.isArray(itemOrData.guidance.tips) && itemOrData.guidance.tips.length > 0) {
        return {
          warning: itemOrData.guidance.summary,
          steps: itemOrData.guidance.tips,
        };
      }
      detectedItem = itemOrData.item || itemOrData.object || itemOrData.name || '';
      if (!category) category = itemOrData.category || itemOrData.class || '';
      if (optionalIsWaste === undefined && itemOrData.is_waste !== undefined) {
        isWaste = itemOrData.is_waste;
      }
    } else if (typeof itemOrData === 'string') {
      detectedItem = itemOrData;
    }

    const itemStr = (detectedItem || '').trim().toLowerCase();
    const catStr = (category || '').trim().toLowerCase();

    // If item is verified non-waste (e.g. human, animal, fresh food, intact usable product)
    if (isWaste === false) {

      // NON-WASTE: Human / Animal
      if (/\b(human|person|people|man|woman|child|boy|girl|animal|dog|cat|bird|rabbit|horse|cow|pig|fish|pet)\b/i.test(itemStr) || catStr.includes('human') || catStr.includes('animal')) {
        return {
          warning: 'Living beings are never classified or handled as waste.',
          steps: [
            'Ensure a safe, healthy, and humane living environment.',
            'Provide appropriate nutrition, hydration, and care for domestic pets.',
            'Contact local animal welfare organizations if an animal requires assistance.',
            'Preserve living specimens in their natural or safe domestic surroundings.',
          ],
        };
      }

      // NON-WASTE: Curtains / Drapes / Blinds / Rugs / Carpets
      if (/\b(curtain|curtains|drape|drapes|blind|blinds|valance|sheer|rug|rugs|carpet|carpets|mat|mats|drapery)\b/i.test(itemStr) || (/\b(curtain|drape|blind|drapery)\b/i.test(catStr))) {
        return {
          warning: 'Curtains and home textiles are usable household items — care for them properly to maximise their lifespan.',
          steps: [
            'Wash according to fabric care label instructions (machine wash, hand wash, or dry-clean only).',
            'Store in a cool, dry, ventilated space to prevent mildew, dust buildup, and colour fading.',
            'When replacing, donate to charity shops, thrift stores, or community donation drives if in good condition.',
            'At end-of-life, deposit in designated textile recycling bins — do not place in general household waste.',
          ],
        };
      }

      // NON-WASTE: Furniture / Chair / Sofa / Table / Shelf / Bed / Cabinet / Desk
      if (/\b(furniture|chair|chairs|sofa|sofas|couch|couches|table|tables|desk|desks|shelf|shelves|cabinet|cabinets|wardrobe|wardrobes|bed|beds|drawer|drawers|bench|benches|stool|stools|rack|racks|bookcase|cupboard)\b/i.test(itemStr) || catStr.includes('furniture')) {
        return {
          warning: 'Usable furniture — maintain in good condition and explore donation or resale before disposal.',
          steps: [
            'Clean and maintain regularly (polish surfaces, tighten joints, treat scratches) to extend functional lifespan.',
            'Repair minor damage — scratches, loose screws, and worn upholstery are often cost-effective to fix.',
            'Donate to charity, second-hand shops, or list on community marketplace platforms if no longer needed.',
            'At end-of-life, arrange for a bulk waste collection or furniture recycling — do not leave on street.',
          ],
        };
      }

      // NON-WASTE: Clothing / Apparel / Shoes / Bags / Accessories
      if (/\b(clothes|clothing|shirt|shirts|dress|dresses|trousers|jeans|skirt|jacket|coat|sweater|hoodie|shoe|shoes|boot|boots|sandal|sandals|bag|bags|handbag|backpack|purse|wallet|belt|hat|cap|scarf|socks|gloves|underwear|apparel|garment|uniform)\b/i.test(itemStr) || (/\b(cloth|textile|apparel|fashion)\b/i.test(catStr))) {
        return {
          warning: 'Wearable clothing and accessories in good condition — donate or resell before considering disposal.',
          steps: [
            'Wash and store according to the garment care label to maintain fabric quality.',
            'Donate to charity organisations, clothing banks, or thrift stores if no longer needed.',
            'Sell or swap through second-hand platforms and community groups to extend useful life.',
            'At end-of-life, deposit in designated textile or clothing recycling collection points.',
          ],
        };
      }

      // NON-WASTE: Books / Magazines / Notebooks
      if (/\b(book|books|magazine|magazines|novel|novels|textbook|textbooks|notebook|notebooks|journal|journals|comic|comics|manual|manuals|guide|encyclopedia|dictionary)\b/i.test(itemStr) || catStr.includes('book')) {
        return {
          warning: 'Usable books and publications — donate, swap, or share rather than discard.',
          steps: [
            'Donate to local libraries, schools, literacy programmes, or community book-swap shelves.',
            'Sell or exchange through second-hand bookshops, online platforms, or neighbourhood groups.',
            'Keep dry and away from direct sunlight to prevent yellowing, warping, and mould.',
            'At end-of-life, remove hard covers or metal rings and place paper content in paper recycling.',
          ],
        };
      }

      // NON-WASTE: Toys / Games / Sporting goods
      if (/\b(toy|toys|game|games|puzzle|puzzles|doll|dolls|action\s*figure|board\s*game|teddy|stuffed|lego|playset|ball|balls|bat|racket|bicycle|bike|scooter|skateboard|sporting|sport)\b/i.test(itemStr) || catStr.includes('toy')) {
        return {
          warning: 'Usable toys and games — clean, donate, or resell to give a second life before disposal.',
          steps: [
            'Clean and sanitise thoroughly before donating to charities, schools, or children\'s programmes.',
            'Check for and remove batteries, disposing of them separately at battery collection points.',
            'Donate to charity organisations, toy drives, or community centres.',
            'At end-of-life, separate plastic, metal, and fabric components for appropriate recycling streams.',
          ],
        };
      }

      // NON-WASTE: Kitchen items / Cookware / Utensils / Appliances
      if (/\b(kitchen|utensil|utensils|cookware|pot|pots|pan|pans|plate|plates|bowl|bowls|cup|cups|mug|mugs|cutlery|fork|spoon|knife|knives|tray|trays|container|containers|appliance|blender|toaster|kettle|microwave|oven|fridge|refrigerator)\b/i.test(itemStr) || (/\b(kitchen|cookware|utensil|appliance)\b/i.test(catStr))) {
        return {
          warning: 'Usable kitchen items — maintain in clean, hygienic condition and consider donating when replacing.',
          steps: [
            'Clean thoroughly after each use and store in dry, covered, hygienic conditions.',
            'Donate to charity kitchens, community organisations, or second-hand shops when replacing.',
            'Repair handles, seals, and minor damage before replacing items prematurely.',
            'At end-of-life, separate metal, plastic, glass, and ceramic components for appropriate recycling.',
          ],
        };
      }

      // NON-WASTE: Electronics / Gadgets (usable, not waste)
      if (/\b(phone|smartphone|tablet|laptop|computer|camera|television|tv|headphones|speaker|remote|charger|keyboard|mouse|gadget|device|console|gaming)\b/i.test(itemStr) || (/\b(electronic|device|gadget)\b/i.test(catStr) && !catStr.includes('waste'))) {
        return {
          warning: 'Working electronics — maintain properly, and donate or resell rather than discard.',
          steps: [
            'Keep software updated and perform regular maintenance to extend device lifespan.',
            'Protect with suitable cases and avoid exposure to moisture, heat, or physical shock.',
            'Donate, resell, or trade in through manufacturer or retailer take-back programmes when upgrading.',
            'At end-of-life, take to a certified e-waste collection centre — never place in general waste.',
          ],
        };
      }

      // NON-WASTE: Plants / Flowers / Potted Plants
      if (/\b(plant|plants|flower|flowers|pot|potted\s*plant|tree|sapling|herb|herbs|cactus|succulent|shrub|fern|garden)\b/i.test(itemStr) || catStr.includes('plant')) {
        return {
          warning: 'Living plant — care for it properly to maintain health and longevity.',
          steps: [
            'Water regularly as per species requirements — avoid over or under-watering.',
            'Place in an appropriate light environment (direct sun, indirect light, or shade).',
            'Repot when roots outgrow current container using suitable, nutrient-rich potting mix.',
            'Prune dead leaves and stems to promote healthy growth and prevent disease spread.',
          ],
        };
      }

      // NON-WASTE: Food / Fresh Produce (usable)
      if (/\b(food|fruit|vegetable|banana|apple|orange|mango|tomato|potato|onion|bread|egg|eggs|milk|cheese|meat|fish|rice|pasta|grain|cereal|snack|produce)\b/i.test(itemStr) || catStr.includes('food') || catStr.includes('organic')) {
        return {
          warning: 'Fresh food or produce — store correctly to maintain freshness and prevent unnecessary waste.',
          steps: [
            'Store in clean, dry, or refrigerated conditions as appropriate for the food type.',
            'Consume before expiration or best-before date to prevent unnecessary food waste.',
            'Prepare peelings and scraps for home composting or municipal organics collection.',
            'Do not discard edible food unnecessarily — share with neighbours or food banks if surplus.',
          ],
        };
      }

      // NON-WASTE: Battery / Hazardous Material (usable, not yet depleted)
      if (/\b(battery|batteries|lithium|li-ion|button\s*cell|coin\s*cell|power\s*cell)\b/i.test(itemStr) || catStr.includes('battery') || catStr.includes('hazardous')) {
        return {
          warning: 'Active battery or hazardous material — handle and store with appropriate safety precautions.',
          steps: [
            'Store in a cool, dry place away from direct sunlight and metal contact surfaces.',
            'Do not puncture, crush, or expose to excessive heat or open flame.',
            'Keep away from children and store in original or clearly labelled packaging.',
            'When depleted or damaged, take to a dedicated battery/hazardous waste drop-off point.',
          ],
        };
      }

      // NON-WASTE: Named item fallback — item name known but no specific rule matched
      const displayName = detectedItem || 'this item';
      return {
        warning: `${displayName} is identified as a usable, non-waste item — care for it properly to extend its lifespan.`,
        steps: [
          `Clean and maintain ${displayName.toLowerCase()} regularly according to manufacturer or care guidelines.`,
          'Store in appropriate conditions (dry, cool, ventilated) to prevent deterioration.',
          'Donate, sell, or give away when no longer personally needed rather than discarding.',
          'At end-of-life, separate materials and place in the correct recycling or disposal stream.',
        ],
      };
    }

    // 1. BATTERY (Exact match & common variations: AA, AAA, Lithium, 9V, Button cell, etc.)
    if (/\b(batter(y|ies)|lithium|li-ion|button\s*cell|coin\s*cell|accumulator|power\s*cell)\b/i.test(itemStr) ||
        (/\b(battery|batteries)\b/i.test(catStr) && !itemStr)) {
      return {
        warning: 'Do not place batteries in regular household trash.',
        steps: [
          'Take the battery to a designated battery/e-waste collection center.',
          'Keep batteries separate from other waste.',
          'Do not crush, puncture, burn, or dismantle the battery.',
          'Store safely until proper disposal is possible.',
        ],
      };
    }

    // 2. CHEMICAL / PAINT / HAZARDOUS WASTE
    if (/\b(paint|paints|paint\s*can|solvent|solvents|thinner|motor\s*oil|engine\s*oil|pesticide|pesticides|insecticide|insecticides|fertilizer|bleach|varnish|chemical|chemicals|corrosive|toxic|flammable|poison)\b/i.test(itemStr) ||
        (/\b(chemical|paint)\b/i.test(catStr))) {
      return {
        warning: 'Toxic and hazardous! Never pour chemicals or paint down household drains, gutters, or onto soil.',
        steps: [
          'Keep in original labeled container with cap sealed tightly to prevent vapor leaks.',
          'Store safely in an upright position in a well-ventilated, secure location away from heat.',
          'Never mix different chemical remnants or household solvents together.',
          'Take directly to an authorized municipal household hazardous waste (HHW) collection facility.',
        ],
      };
    }

    // 3. ELECTRONIC WASTE / LAPTOP / GADGETS
    if (/\b(e-waste|electronic|electronics|laptop|laptops|computer|computers|pc|desktop|smartphone|smartphones|cell\s*phone|mobile\s*phone|tablet|tablets|ipad|circuit|motherboard|printer|printers|monitor|monitors|television|tv|charger|chargers|keyboard|mouse|headphones|earbuds|hard\s*drive)\b/i.test(itemStr) ||
        (/\b(electronic|e-waste)\b/i.test(catStr))) {
      return {
        warning: 'Do not discard electronics in municipal trash; contains toxic heavy metals and recyclable rare components.',
        steps: [
          'Back up personal data and perform a permanent factory wipe on digital storage devices.',
          'Remove batteries if detachable and dispose of them in dedicated battery drop-offs.',
          'Bring to certified e-waste drop-off centers, electronics retailers, or municipal collection events.',
          'Never dismantle, crush screens, or burn electronic circuit boards.',
        ],
      };
    }

    // 4. MEDICAL / BIOMEDICAL WASTE
    if (/\b(syringe|syringes|needle|needles|sharps|medicine|medicines|pill|pills|blister\s*pack|mask|masks|bandage|bandages|biomedical|clinical)\b/i.test(itemStr)) {
      return {
        warning: 'Biohazard risk! Keep protected to prevent pathogen transmission or needle injury.',
        steps: [
          'Place sharps and needles in a puncture-proof, rigid biohazard container.',
          'Return unused or expired medications to pharmacy drop-off collection boxes.',
          'Never flush medications down toilets or discard loose sharps in household trash.',
          'Follow municipal biohazard disposal protocols for specialized clinical handling.',
        ],
      };
    }

    // 5. PLASTIC BOTTLE (Specific bottle matching before generic plastic)
    if (/\b(plastic\s*bottle|pet\s*bottle|water\s*bottle|soda\s*bottle|beverage\s*bottle|plastic\s*jug|milk\s*jug|detergent\s*bottle|shampoo\s*bottle)\b/i.test(itemStr) ||
        (/\bbottle\b/i.test(itemStr) && (/\b(plastic|pet)\b/i.test(itemStr) || /\b(plastic|pet)\b/i.test(catStr))) ||
        (itemStr === 'bottle' && !catStr.includes('glass'))) {
      return {
        warning: 'Empty and rinse before placing in plastic recycling.',
        steps: [
          'Empty all residual liquids and rinse the bottle clean.',
          'Remove plastic caps and non-recyclable wraps if required locally.',
          'Crush or flatten the bottle to reduce volume and save bin space.',
          'Deposit into designated plastic or blue recycling stream.',
        ],
      };
    }

    // 6a. PICTURE FRAME / MIRROR / BROKEN GLASS
    if (/\b(picture\s*frame|photo\s*frame|picture\s*frames|photo\s*frames|mirror|mirrors|framed\s*glass|broken\s*frame|broken\s*glass|window\s*glass|window\s*pane|glass\s*frame|frame)\b/i.test(itemStr)) {
      return {
        warning: 'Broken glass is sharp and hazardous \u2014 wrap securely before disposal and never place loose shards in recycling bins.',
        steps: [
          'Wear thick gloves when handling broken glass to avoid cuts and lacerations.',
          "Wrap all glass fragments tightly in several layers of newspaper, seal with tape, and label as 'Broken Glass'.",
          'Separate the wooden, plastic, or metal frame from the glass and recycle frame materials individually.',
          'Dispose of sealed glass waste in a rigid container or at a designated glass/hazardous waste drop-off site.',
        ],
      };
    }

    // 6b. GLASS / GLASS BOTTLE
    if (/\b(glass|glasses|glass\s*bottle|glass\s*jar|wine\s*bottle|beer\s*bottle|glassware|mason\s*jar)\b/i.test(itemStr) ||
        (/\bglass\b/i.test(catStr) && !itemStr.includes('plastic'))) {
      return {
        warning: 'Handle carefully to avoid breakage; do not mix window glass or ceramics with bottle recycling.',
        steps: [
          'Empty and rinse the glass bottle or jar with clean water.',
          'Remove plastic or metal lids and corks (recycle metal/plastic separately).',
          'Keep glass colors separated (flint/clear, amber/brown, green) if required locally.',
          'Place unbroken in designated glass bottle banks or curbside collection.',
        ],
      };
    }

    // 7. METAL / ALUMINIUM CAN
    if (/\b(metal|metals|aluminium|aluminum|tin|tins|steel|can|cans|soda\s*can|beer\s*can|beverage\s*can|food\s*can|tin\s*can|aerosol|foil|scrap\s*metal|brass|copper|iron)\b/i.test(itemStr) ||
        (/\bmetal\b/i.test(catStr) && !itemStr.includes('plastic'))) {
      return {
        warning: 'Rinse metal containers thoroughly to eliminate food, grease, or chemical residue.',
        steps: [
          'Rinse out liquids, food residue, or oils completely.',
          'Do not crush aerosol cans or puncture pressurized canisters.',
          'Recycle metal lids inside the can or attach securely to prevent sharp edges.',
          'Place in designated metal recycling or curbside dry recyclables collection.',
        ],
      };
    }

    // 8. PAPER / CARDBOARD
    if (/\b(paper|cardboard|carton|cartons|newspaper|newspapers|magazine|magazines|paper\s*bag|office\s*paper|kraft|envelope|envelopes|flyer|flyers|box|boxes)\b/i.test(itemStr) ||
        (/\b(paper|cardboard)\b/i.test(catStr))) {
      return {
        warning: 'Keep paper clean, dry, and free of food grease, wax, or oil.',
        steps: [
          'Flatten cardboard boxes and remove plastic packing tape or bubble wrap.',
          'Keep paper dry; soiled or greasy paper (e.g. pizza boxes) must be composted, not recycled.',
          'Remove plastic window films, spiral bindings, and large metal clips.',
          'Deposit in the dedicated paper and cardboard recycling bin.',
        ],
      };
    }

    // 9. GENERAL PLASTIC
    if (/\b(plastic|plastics|polythene|polyethylene|polypropylene|styrofoam|polystyrene|pvc|tupperware)\b/i.test(itemStr) ||
        (/\bplastic\b/i.test(catStr))) {
      return {
        warning: 'Clean thoroughly and check resin identification code (1-7) before recycling.',
        steps: [
          'Scrape out and rinse all food, oil, or chemical residue.',
          'Separate flexible soft film and bags from rigid plastic containers.',
          'Keep plastic clean and dry to avoid contaminating recycling batches.',
          'Deposit in dedicated municipal plastic recycling or drop-off bins.',
        ],
      };
    }

    // 10a. FISH / MEAT / ANIMAL-BASED FOOD WASTE (before generic organic)
    if (/\b(fish|fishes|fish\s*head|fish\s*heads|viscera|entrails|guts|offal|shellfish|shrimp|prawn|crab|lobster|squid|meat|chicken|poultry|mutton|pork|beef|lamb|bone|bones|carcass)\b/i.test(itemStr)) {
      return {
        warning: 'Fish and meat waste decomposes rapidly, produces strong odours, and attracts pests \u2014 handle with urgency and hygiene.',
        steps: [
          'Wrap tightly in newspaper or biodegradable bags to contain odour and prevent leakage.',
          'Store in a sealed, lidded container and keep refrigerated or frozen until collection day if possible.',
          'Place in organic/wet waste bins on scheduled collection days \u2014 never leave exposed in open bins.',
          'Do not mix with dry recyclables; dispose separately to avoid contaminating recycling streams.',
        ],
      };
    }

    // 10b. ORGANIC WASTE / FOOD WASTE (generic plant-based / compostable)
    if (/\b(organic|food|fruit|fruits|vegetable|vegetables|banana|apple|orange|peel|peels|scraps|leftover|leftovers|compost|compostable|biodegradable|egg\s*shell|eggshell|coffee\s*grounds|tea\s*bag|leaves|plant|plants|garden\s*waste)\b/i.test(itemStr) ||
        (/\b(organic|food|compost)\b/i.test(catStr))) {
      return {
        warning: 'Keep organic materials separated from plastics, glass, and non-biodegradable packaging.',
        steps: [
          'Collect food scraps, fruit peels, and garden trimmings in a dedicated compost bin.',
          'Do not include plastic bags, synthetic stickers, or chemically treated wrappers.',
          'Deposit into green composting bins, backyard compost piles, or municipal bio-waste.',
          'Layer with dry carbon materials (leaves, sawdust) to accelerate natural aerobic breakdown.',
        ],
      };
    }

    // 11. TEXTILE / CLOTHING
    if (/\b(clothes|clothing|textile|textiles|fabric|fabrics|shirt|pants|shoe|shoes|jacket|towel|apparel)\b/i.test(itemStr)) {
      return {
        warning: 'Keep textiles clean and dry to allow fabric recycling or charitable donation.',
        steps: [
          'If wearable, donate to local charities, clothing drives, or thrift organizations.',
          'Ensure items are clean and completely dry to prevent mold growth.',
          'For torn or unwearable fabrics, deposit in designated textile recycling bins.',
          'Do not discard into mixed landfill trash.',
        ],
      };
    }

    // 12. DYNAMIC ITEM-SPECIFIC FALLBACK FOR ANY DETECTED WASTE ITEM
    const itemName = (detectedItem || '').trim() || (catStr.includes('organic') ? 'Organic Material' : (catStr.includes('hazard') ? 'Hazardous Specimen' : 'Recyclable Specimen'));
    const itemLower = itemName.toLowerCase();

    if (catStr.includes('hazard')) {
      return {
        warning: `Potentially hazardous ${itemLower} — handle with protective care and never mix with domestic trash.`,
        steps: [
          `Take ${itemLower} to a designated municipal hazardous waste collection facility.`,
          `Keep ${itemLower} sealed and isolated from domestic waste streams to prevent chemical reactions.`,
          `Avoid direct skin contact, inhalation of fumes, or puncturing the item.`,
          `Consult local municipal hazardous waste collection schedules for specialized drop-off days.`,
        ],
      };
    }

    if (catStr.includes('organic') || catStr.includes('food') || catStr.includes('compost')) {
      return {
        warning: `Separate ${itemLower} from plastics, glass, and non-biodegradable packaging.`,
        steps: [
          `Collect ${itemLower} in a dedicated compost bin or bio-waste container.`,
          `Ensure free of plastic wrap, synthetic stickers, or chemical wrappers.`,
          `Deposit into green composting bins, backyard compost piles, or municipal bio-waste.`,
          `Dispose promptly or refrigerate to contain odor buildup and deter pests.`,
        ],
      };
    }

    return {
      warning: `Prepare ${itemLower} properly to support material recycling and circular recovery.`,
      steps: [
        `Empty and rinse ${itemLower} thoroughly to eliminate liquids or residues.`,
        `Separate composite materials (caps, lids, labels) where required locally.`,
        `Flatten or consolidate ${itemLower} to optimize space in recycling containers.`,
        `Place into the appropriate dry recyclables collection or community recycling point.`,
      ],
    };
  }

  // Export globally for programmatic reuse & automated testing
  if (typeof window !== 'undefined') {
    window.getDisposalProtocol = getDisposalProtocol;
  }

  // --- 5. Render Inference Results & Dashboard ---
  function renderInferenceResults(data) {
    showResultsState();
    currentRequestId = null;

    const timestampEl = document.getElementById('inferenceTimestamp');
    if (timestampEl) {
      const now = new Date();
      timestampEl.textContent = `Timestamp: ${now.toLocaleTimeString()}`;
    }

    // Status: OK (Verified Classification)
    if (unclearResultBanner) unclearResultBanner.style.display = 'none';
    if (confidentResultSection) confidentResultSection.style.display = 'block';

    const proIntelCard = document.getElementById('proIntelCard');
    const resultIconBox = document.getElementById('resultIconBox');
    const intelObjectTitle = document.getElementById('intelObjectTitle');
    const intelCategoryPill = document.getElementById('intelCategoryPill');
    const intelConditionText = document.getElementById('intelConditionText');
    const proDecisionBadge = document.getElementById('proDecisionBadge');
    const proDecisionValue = document.getElementById('proDecisionValue');
    const verificationBadge = document.getElementById('verificationBadge');

    // 5 Telemetry Field Elements
    const telemetryObject = document.getElementById('telemetryObject');
    const telemetryCondition = document.getElementById('telemetryCondition');
    const telemetryIsWaste = document.getElementById('telemetryIsWaste');
    const telemetryCategory = document.getElementById('telemetryCategory');
    const telemetryReason = document.getElementById('telemetryReason');

    // Detected item name (Primary key for protocols)
    const detectedItemName = data.item || data.object || '';

    // Determine category themes & colors (Harmonized by item + category)
    let categoryColor = '#059669';
    let categoryBg = '#ECFDF5';
    let categoryBorder = '#A7F3D0';

    const itemStr = detectedItemName.toLowerCase();
    const catStr = (data.category || data.class || '').toLowerCase();
    const combinedStr = itemStr + ' ' + catStr;

    if (combinedStr.includes('hazard') || combinedStr.includes('battery') || combinedStr.includes('paint') || combinedStr.includes('chemical') || combinedStr.includes('toxic') || combinedStr.includes('e-waste') || combinedStr.includes('laptop') || combinedStr.includes('electronic')) {
      categoryColor = '#EF4444';
      categoryBg = '#FEF2F2';
      categoryBorder = '#FECACA';
    } else if (combinedStr.includes('recyclable') || combinedStr.includes('plastic') || combinedStr.includes('paper') || combinedStr.includes('metal') || combinedStr.includes('glass') || combinedStr.includes('can') || combinedStr.includes('bottle') || combinedStr.includes('cardboard')) {
      categoryColor = '#2563EB';
      categoryBg = '#EFF6FF';
      categoryBorder = '#BFDBFE';
    } else if (combinedStr.includes('organic') || combinedStr.includes('food') || combinedStr.includes('animal') || combinedStr.includes('human') || combinedStr.includes('compost') || combinedStr.includes('banana') || combinedStr.includes('fruit')) {
      categoryColor = '#059669';
      categoryBg = '#ECFDF5';
      categoryBorder = '#A7F3D0';
    }

    if (proIntelCard) {
      proIntelCard.style.setProperty('--result-color', categoryColor);
      proIntelCard.style.setProperty('--result-bg', categoryBg);
      proIntelCard.style.setProperty('--result-border', categoryBorder);
    }

    if (resultIconBox) {
      if (data.is_waste) {
        if (combinedStr.includes('hazard') || combinedStr.includes('battery') || combinedStr.includes('chemical') || combinedStr.includes('paint')) {
          resultIconBox.innerHTML = '<i class="bi bi-radioactive" style="color:var(--hazardous-color);"></i>';
        } else if (combinedStr.includes('organic') || combinedStr.includes('food') || combinedStr.includes('banana')) {
          resultIconBox.innerHTML = '<i class="bi bi-tree-fill" style="color:var(--organic-color);"></i>';
        } else {
          resultIconBox.innerHTML = '<i class="bi bi-recycle" style="color:var(--brand-primary);"></i>';
        }
      } else {
        resultIconBox.innerHTML = '<i class="bi bi-check-circle-fill" style="color:var(--brand-primary);"></i>';
      }
    }

    const formattedObjName = detectedItemName || 'Identified Specimen';
    if (intelObjectTitle) intelObjectTitle.textContent = formattedObjName;

    const categoryText = data.category || (data.class ? `${data.class} Waste` : 'Material Identified');
    if (intelCategoryPill) {
      intelCategoryPill.textContent = categoryText;
      intelCategoryPill.style.color = categoryColor;
    }

    if (intelConditionText) {
      intelConditionText.textContent = data.condition || (data.is_waste ? 'Used / Discarded' : 'Fresh / Usable');
    }

    if (proDecisionBadge && proDecisionValue) {
      if (data.is_waste) {
        proDecisionBadge.className = 'pro-decision-badge pro-decision-badge--yes';
        proDecisionValue.textContent = 'YES';
      } else {
        proDecisionBadge.className = 'pro-decision-badge pro-decision-badge--no';
        proDecisionValue.textContent = 'NO';
      }
    }

    // Dynamic contextual icon for object card
    const metricObjectIcon = document.querySelector('.pro-prop-cell:nth-child(1) .pro-prop-icon');
    const metricCategoryIcon = document.querySelector('.pro-prop-cell:nth-child(4) .pro-prop-icon');
    if (metricObjectIcon) {
      if (combinedStr.includes('battery')) metricObjectIcon.innerHTML = '<i class="bi bi-battery-charging"></i>';
      else if (combinedStr.includes('laptop') || combinedStr.includes('phone') || combinedStr.includes('electronic') || combinedStr.includes('computer')) metricObjectIcon.innerHTML = '<i class="bi bi-laptop"></i>';
      else if (combinedStr.includes('food') || combinedStr.includes('organic') || combinedStr.includes('banana') || combinedStr.includes('apple')) metricObjectIcon.innerHTML = '<i class="bi bi-flower1"></i>';
      else if (combinedStr.includes('plastic') || combinedStr.includes('bottle')) metricObjectIcon.innerHTML = '<i class="bi bi-cup-straw"></i>';
      else if (combinedStr.includes('metal') || combinedStr.includes('can') || combinedStr.includes('tin')) metricObjectIcon.innerHTML = '<i class="bi bi-archive-fill"></i>';
      else if (combinedStr.includes('paper') || combinedStr.includes('cardboard')) metricObjectIcon.innerHTML = '<i class="bi bi-file-earmark-text"></i>';
      else if (combinedStr.includes('glass')) metricObjectIcon.innerHTML = '<i class="bi bi-cup"></i>';
      else if (combinedStr.includes('chemical') || combinedStr.includes('paint')) metricObjectIcon.innerHTML = '<i class="bi bi-radioactive"></i>';
      else if (combinedStr.includes('animal') || combinedStr.includes('human')) metricObjectIcon.innerHTML = '<i class="bi bi-heart-pulse-fill"></i>';
      else metricObjectIcon.innerHTML = '<i class="bi bi-box-seam"></i>';
    }
    if (metricCategoryIcon) {
      if (combinedStr.includes('hazard') || combinedStr.includes('battery') || combinedStr.includes('chemical') || combinedStr.includes('paint') || combinedStr.includes('laptop')) metricCategoryIcon.innerHTML = '<i class="bi bi-radioactive"></i>';
      else if (combinedStr.includes('organic') || combinedStr.includes('food')) metricCategoryIcon.innerHTML = '<i class="bi bi-tree-fill"></i>';
      else if (combinedStr.includes('recyclable') || combinedStr.includes('plastic') || combinedStr.includes('paper') || combinedStr.includes('metal') || combinedStr.includes('glass')) metricCategoryIcon.innerHTML = '<i class="bi bi-recycle"></i>';
      else if (combinedStr.includes('animal') || combinedStr.includes('human')) metricCategoryIcon.innerHTML = '<i class="bi bi-heart-pulse-fill"></i>';
      else metricCategoryIcon.innerHTML = '<i class="bi bi-tags-fill"></i>';
    }

    // Populate 4 Telemetry Metrics + Reason
    if (telemetryObject) telemetryObject.textContent = formattedObjName;
    if (telemetryCondition) telemetryCondition.textContent = data.condition || 'Identified';
    if (telemetryIsWaste) {
      telemetryIsWaste.textContent = data.is_waste ? 'Yes (Waste Item)' : 'No (Usable / Living)';
      telemetryIsWaste.style.color = data.is_waste ? '#DC2626' : '#059669';
    }
    if (telemetryCategory) telemetryCategory.textContent = categoryText;
    if (telemetryReason) telemetryReason.textContent = data.reason || 'Specimen processed through multi-step intelligence model.';

    if (verificationBadge) {
      if (data.is_waste) {
        verificationBadge.className = 'badge';
        verificationBadge.style.background = '#FEF2F2';
        verificationBadge.style.border = '1px solid #FECACA';
        verificationBadge.style.color = '#DC2626';
        verificationBadge.innerHTML = `<span class="status-dot" style="background:#DC2626; box-shadow:0 0 6px rgba(220,38,38,0.7);"></span> Waste Discard Directive`;
      } else {
        verificationBadge.className = 'badge';
        verificationBadge.style.background = '#ECFDF5';
        verificationBadge.style.border = '1px solid #A7F3D0';
        verificationBadge.style.color = '#059669';
        verificationBadge.innerHTML = `<span class="status-dot" style="background:#059669; box-shadow:0 0 6px rgba(5,150,105,0.7);"></span> Material Preservation Protocol`;
      }
    }

    // Probability Bars (Show when probabilities exist)
    const probCard = document.getElementById('probDistributionCard');
    const barsContainer = document.getElementById('probabilityBars');

    if (data.probabilities && Object.keys(data.probabilities).length > 0) {
      if (probCard) probCard.style.display = 'block';
      if (barsContainer) {
        barsContainer.innerHTML = '';
        const classThemeColors = {
          Hazardous: '#EF4444',
          Organic: '#10B981',
          Recyclable: '#2563EB',
        };

        Object.entries(data.probabilities).forEach(([cls, pct]) => {
          const row = document.createElement('div');
          row.className = 'prob-row-saas';
          const isDominant = cls === data.class;
          row.innerHTML = `
            <div class="prob-class-name">
              <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${classThemeColors[cls]};"></span>
              <span style="${isDominant ? 'font-weight:700; color:' + classThemeColors[cls] : ''}">${cls}</span>
            </div>
            <div class="prob-track-saas">
              <div class="prob-fill-saas" style="width: 0%; background: ${classThemeColors[cls]};"></div>
            </div>
            <div class="prob-pct-label" style="${isDominant ? 'font-weight:700; color:' + classThemeColors[cls] : ''}">${pct}%</div>
          `;
          barsContainer.appendChild(row);

          setTimeout(() => {
            const fill = row.querySelector('.prob-fill-saas');
            if (fill) fill.style.width = `${pct}%`;
          }, 50);
        });
      }
    } else if (probCard) {
      probCard.style.display = 'none';
    }

    // ==========================================================================
    // Dynamic Actionable Disposal Protocol UI Rendering
    // Prioritizes the AI-generated item-specific protocol from API, with fallback
    // ==========================================================================
    let protocol = null;
    if (data && data.protocol && data.protocol.warning && Array.isArray(data.protocol.instructions) && data.protocol.instructions.length > 0) {
      protocol = {
        warning: data.protocol.warning,
        steps: data.protocol.instructions,
      };
    } else if (data && data.guidance && data.guidance.summary && Array.isArray(data.guidance.tips) && data.guidance.tips.length > 0) {
      protocol = {
        warning: data.guidance.summary,
        steps: data.guidance.tips,
      };
    } else {
      protocol = getDisposalProtocol(detectedItemName, data.category || data.class, data.is_waste);
    }

    const guidanceHeadingText = document.getElementById('guidanceHeadingText');
    const guidanceSummary = document.getElementById('guidanceSummary');
    const guidanceTips = document.getElementById('guidanceTips');

    if (guidanceHeadingText) {
      guidanceHeadingText.textContent = data.is_waste ? 'Actionable Disposal Protocol' : 'Material Handling & Care Directive';
    }

    if (guidanceSummary) {
      guidanceSummary.textContent = protocol.warning;
      guidanceSummary.style.color = categoryColor;
    }

    if (guidanceTips && protocol.steps) {
      guidanceTips.innerHTML = '';
      protocol.steps.forEach(step => {
        const li = document.createElement('li');
        li.className = 'guidance-tip-item';
        li.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="${categoryColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          <span>${step}</span>
        `;
        guidanceTips.appendChild(li);
      });
    }

    // Toggle "Find Disposal Location" button visibility based on is_waste
    const findDisposalBtn = document.getElementById('findDisposalLocationBtn');
    const findDisposalBtnText = document.getElementById('findDisposalBtnText');
    const disposalTrackerCard = document.getElementById('disposalTrackerCard');

    if (findDisposalBtn) {
      if (data.is_waste) {
        findDisposalBtn.style.display = 'inline-flex';
        findDisposalBtn.disabled = false;
        if (findDisposalBtnText) findDisposalBtnText.textContent = 'Find Disposal Location';
      } else {
        findDisposalBtn.style.display = 'none';
        closeDisposalTrackerModal();
      }
    }
  }

  // --- 6. Find Disposal Location Modal Box (Popup Dialog) ---
  const findDisposalBtn = document.getElementById('findDisposalLocationBtn');
  const findDisposalBtnText = document.getElementById('findDisposalBtnText');
  const disposalTrackerModalOverlay = document.getElementById('disposalTrackerModalOverlay');
  let currentRequestId = null;
  let detectMapInstance = null;

  function openDisposalTrackerModal() {
    const overlay = document.getElementById('disposalTrackerModalOverlay');
    if (overlay) {
      overlay.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      setTimeout(() => {
        if (detectMapInstance) {
          detectMapInstance.invalidateSize();
        }
      }, 150);
    }
  }
  window.openDisposalTrackerModal = openDisposalTrackerModal;

  function closeDisposalTrackerModal() {
    const overlay = document.getElementById('disposalTrackerModalOverlay');
    if (overlay) {
      overlay.style.display = 'none';
      document.body.style.overflow = '';
    }
  }
  window.closeDisposalTrackerModal = closeDisposalTrackerModal;

  if (disposalTrackerModalOverlay) {
    disposalTrackerModalOverlay.addEventListener('click', (e) => {
      if (e.target === disposalTrackerModalOverlay) closeDisposalTrackerModal();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDisposalTrackerModal();
    }
  });

  if (findDisposalBtn) {
    findDisposalBtn.addEventListener('click', async () => {
      if (!lastPredictionData) return;

      // If already submitted for this detection result, open the tracker box immediately
      if (currentRequestId) {
        openDisposalTrackerModal();
        return;
      }

      findDisposalBtn.disabled = true;
      if (findDisposalBtnText) findDisposalBtnText.textContent = 'Locating Facility...';

      const payload = {
        object_name: lastPredictionData.object || 'Waste Item',
        category: lastPredictionData.category || lastPredictionData.class || 'Waste',
        image_url: lastPredictionData.image_url || '',
        classification_id: lastPredictionData.classification_id || null
      };

      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

      try {
        const res = await fetch('/api/disposal/request', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify(payload)
        });

        const resData = await res.json();
        if (!res.ok) {
          if (resData.location_required) {
            findDisposalBtn.disabled = false;
            if (findDisposalBtnText) findDisposalBtnText.textContent = 'Find Disposal Location';
            if (typeof openQuickLocationModal === 'function') {
              openQuickLocationModal(() => {
                findDisposalBtn.click();
              });
            } else {
              window.location.href = '/collection-requests';
            }
            return;
          } else {
            showStatusAlert(resData.error || 'Failed to submit disposal request.', 'error');
          }
          findDisposalBtn.disabled = false;
          if (findDisposalBtnText) findDisposalBtnText.textContent = 'Find Disposal Location';
          return;
        }

        const req = resData.request;
        currentRequestId = req.id;

        findDisposalBtn.disabled = false;
        if (findDisposalBtnText) findDisposalBtnText.textContent = 'View Disposal Location';

        // Render Tracker & open modal box
        renderDisposalTracker(req, resData.nearby_locations || []);
        renderNearbyFacilities(resData.nearby_locations || [], req.assigned_location_id, req.user_lat, req.user_lng);
        openDisposalTrackerModal();

      } catch (err) {
        console.error(err);
        showStatusAlert('Network error while creating disposal request.', 'error');
        findDisposalBtn.disabled = false;
        if (findDisposalBtnText) findDisposalBtnText.textContent = 'Find Disposal Location';
      }
    });
  }

  function renderDisposalTracker(req, nearbyLocations) {
    nearbyLocations = nearbyLocations || [];

    const reqBadge = document.getElementById('trackerRequestIdBadge');
    const statusBadge = document.getElementById('trackerStatusBadge');
    const itemSummary = document.getElementById('trackerItemSummary');
    const coordsText = document.getElementById('trackerCoordsText');
    const progressBar = document.getElementById('stepperProgressBar');

    const stepPending = document.getElementById('stepPending');
    const stepReviewed = document.getElementById('stepReviewed');
    const stepAssigned = document.getElementById('stepAssigned');
    const stepCompleted = document.getElementById('stepCompleted');

    const pendingMsg = document.getElementById('trackerPendingMsg');
    const assignedBox = document.getElementById('trackerAssignedBox');

    if (reqBadge) reqBadge.textContent = `#REQ-${req.id}`;
    if (itemSummary) itemSummary.textContent = `${req.object_name} (${req.category})`;
    if (coordsText) coordsText.textContent = `${req.user_lat.toFixed(4)}, ${req.user_lng.toFixed(4)}`;

    // Status & Progress logic
    let pct = '0%';
    [stepPending, stepReviewed, stepAssigned, stepCompleted].forEach(s => s && s.classList.remove('active'));

    if (stepPending) stepPending.classList.add('active');

    if (req.status === 'Pending') {
      pct = '0%';
      if (statusBadge) {
        statusBadge.className = 'badge badge-warning';
        statusBadge.textContent = 'Pending Review';
      }
    } else if (req.status === 'Reviewed') {
      pct = 'calc((100% - 80px) * 0.3333)';
      if (stepReviewed) stepReviewed.classList.add('active');
      if (statusBadge) {
        statusBadge.className = 'badge';
        statusBadge.style.background = 'rgba(37,99,235,0.1)';
        statusBadge.style.color = '#2563EB';
        statusBadge.textContent = 'Reviewed';
      }
    } else if (req.status === 'Location Assigned') {
      pct = 'calc((100% - 80px) * 0.6667)';
      if (stepReviewed) stepReviewed.classList.add('active');
      if (stepAssigned) stepAssigned.classList.add('active');
      if (statusBadge) {
        statusBadge.className = 'badge badge-primary';
        statusBadge.textContent = 'Location Assigned';
      }
    } else if (req.status === 'Completed') {
      pct = 'calc(100% - 80px)';
      if (stepReviewed) stepReviewed.classList.add('active');
      if (stepAssigned) stepAssigned.classList.add('active');
      if (stepCompleted) stepCompleted.classList.add('active');
      if (statusBadge) {
        statusBadge.className = 'badge badge-organic';
        statusBadge.textContent = 'Completed';
      }
    }

    if (progressBar) progressBar.style.width = pct;

    // Show assigned box if facility is assigned
    if (req.assigned_location_id && req.location_name) {
      if (pendingMsg) pendingMsg.style.display = 'none';
      if (assignedBox) assignedBox.style.display = 'block';

      const centerName = document.getElementById('trackerCenterName');
      const centerAddr = document.getElementById('trackerCenterAddress');
      const centerHours = document.getElementById('trackerCenterHours');
      const centerPhone = document.getElementById('trackerCenterPhone');
      const adminNotes = document.getElementById('trackerAdminNotes');
      const distBadge = document.getElementById('trackerDistanceBadge');
      const directionsLink = document.getElementById('trackerDirectionsLink');

      if (centerName) centerName.textContent = req.location_name;
      if (centerAddr) centerAddr.textContent = `${req.location_address} (${req.location_city || 'Metro Area'})`;
      if (centerHours) centerHours.textContent = req.location_hours || 'Mon-Sat: 08:00 - 18:00';
      if (centerPhone) centerPhone.textContent = req.location_phone || 'N/A';
      if (adminNotes) adminNotes.textContent = req.admin_notes || 'Assigned to nearest verified recycling facility.';
      if (distBadge && req.distance_km !== null) distBadge.textContent = `~${req.distance_km} km away`;

      if (directionsLink) {
        directionsLink.href = `https://www.google.com/maps/dir/?api=1&origin=${req.user_lat},${req.user_lng}&destination=${req.location_lat},${req.location_lng}`;
      }

      // Initialize map preview
      setTimeout(() => {
        initTrackerMap(
          req.user_lat, req.user_lng,
          req.location_lat, req.location_lng,
          req.location_name, req.object_name,
          req.location_category, nearbyLocations, req.assigned_location_id
        );
      }, 100);

    } else {
      if (pendingMsg) pendingMsg.style.display = 'block';
      if (assignedBox) assignedBox.style.display = 'none';
      const nearbyWrap = document.getElementById('trackerNearbyWrap');
      if (nearbyWrap) nearbyWrap.style.display = 'none';
    }
  }

  function renderNearbyFacilities(locations, assignedLocId, userLat, userLng) {
    const wrap = document.getElementById('trackerNearbyWrap');
    const list = document.getElementById('trackerNearbyList');
    if (!wrap || !list) return;

    // Show only the ones that aren't the already-assigned facility
    const others = (locations || []).filter(loc => loc.id !== assignedLocId).slice(0, 3);

    if (others.length === 0) {
      wrap.style.display = 'none';
      return;
    }

    list.innerHTML = '';
    others.forEach(loc => {
      const meta = getFacilityMarkerMeta(loc.category);
      const item = document.createElement('div');
      item.style.cssText = 'display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 12px; border:1px solid var(--border-subtle); border-radius:8px; background:var(--bg-surface-subtle);';
      const matchTag = loc.is_category_match ? '<span style="color:#2563EB; font-weight:700;"><i class="bi bi-star-fill" style="font-size:0.75rem;"></i> Compatible</span> &bull; ' : '';
      const directionsUrl = `https://www.google.com/maps/dir/?api=1&origin=${userLat},${userLng}&destination=${loc.latitude},${loc.longitude}`;
      item.innerHTML = `
        <div style="min-width:0;">
          <div style="font-weight:700; font-size:0.85rem; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"><i class="${meta.iconClass}" style="color:${meta.color}; margin-right:5px;"></i>${loc.name}</div>
          <div style="font-size:0.76rem; color:var(--text-muted);">${matchTag}${loc.distance_km} km away</div>
        </div>
        <a href="${directionsUrl}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" style="flex-shrink:0; padding:5px 10px; font-size:0.76rem;">Directions</a>
      `;
      list.appendChild(item);
    });
    wrap.style.display = 'block';
  }

  // Maps a disposal-location category to the Bootstrap Icon class + brand color
  function getFacilityMarkerMeta(category) {
    const cat = (category || '').toLowerCase();
    if (cat.includes('hazard')) {
      return { iconClass: 'bi bi-radioactive', color: '#EF4444', label: 'Hazardous Waste Facility' };
    }
    if (cat.includes('organic')) {
      return { iconClass: 'bi bi-tree-fill', color: '#10B981', label: 'Organic Waste Facility' };
    }
    if (cat.includes('recycl')) {
      return { iconClass: 'bi bi-recycle', color: '#2563EB', label: 'Recycling Center' };
    }
    return { iconClass: 'bi bi-building', color: '#6B7280', label: 'Disposal Facility' };
  }

  function makeFacilityDivIcon(meta, size) {
    size = size || 28;
    const iconSize = Math.max(12, Math.round(size * 0.52));
    return L.divIcon({
      className: 'custom-map-center-pin',
      html: `<div style="background:${meta.color}; width:${size}px; height:${size}px; border-radius:50%; border:3px solid #fff; box-shadow:0 2px 8px rgba(0,0,0,0.35); display:flex; align-items:center; justify-content:center; color:#fff; font-size:${iconSize}px; line-height:1;"><i class="${meta.iconClass}"></i></div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2]
    });
  }

  // Draws the "You are here" -> facility connector. Tries a real routed
  // road path via OSRM's public routing API first (so the line follows
  // actual roads); if that's unreachable, falls back to the previous
  // straight dashed line so the map still shows a connection.
  async function drawRouteOrFallback(map, userLat, userLng, destLat, destLng, color) {
    try {
      const url = `https://router.project-osrm.org/route/v1/driving/${userLng},${userLat};${destLng},${destLat}?overview=full&geometries=geojson`;
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        const coords = data && data.routes && data.routes[0] && data.routes[0].geometry && data.routes[0].geometry.coordinates;
        if (coords && coords.length > 1) {
          const latlngs = coords.map(([lng, lat]) => [lat, lng]);
          const routeLine = L.polyline(latlngs, { color, weight: 4, opacity: 0.8 }).addTo(map);
          // The real road path can swing wider than the straight-line
          // bounds used for the initial fit — extend the view to fit it.
          try { map.fitBounds(routeLine.getBounds().pad(0.15)); } catch (e) { /* ignore */ }
          return routeLine;
        }
      }
    } catch (e) {
      console.warn('Live route lookup unavailable, using straight-line fallback:', e.message);
    }

    // Fallback: straight dashed line between the two points.
    return L.polyline([[userLat, userLng], [destLat, destLng]], {
      color,
      weight: 3,
      opacity: 0.7,
      dashArray: '6, 6'
    }).addTo(map);
  }

  function initTrackerMap(userLat, userLng, locLat, locLng, locName, objName, locCategory, nearbyLocations, assignedLocId) {
    const mapEl = document.getElementById('detectMapPreview');
    if (!mapEl) return;
    nearbyLocations = nearbyLocations || [];

    if (detectMapInstance) {
      detectMapInstance.remove();
      detectMapInstance = null;
    }

    try {
      detectMapInstance = L.map(mapEl, { scrollWheelZoom: false }).setView([(userLat + locLat) / 2, (userLng + locLng) / 2], 12);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(detectMapInstance);

      const userIcon = L.divIcon({
        className: 'custom-map-user-pin',
        html: '<div style="background:#2563EB; width:22px; height:22px; border-radius:50%; border:3px solid #fff; box-shadow:0 2px 6px rgba(0,0,0,0.3); display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px;"><i class="bi bi-geo-alt-fill"></i></div>',
        iconSize: [22, 22],
        iconAnchor: [11, 11]
      });

      const assignedMeta = getFacilityMarkerMeta(locCategory);
      const centerIcon = makeFacilityDivIcon(assignedMeta, 28);

      const uMarker = L.marker([userLat, userLng], { icon: userIcon }).addTo(detectMapInstance);
      uMarker.bindPopup('<b><i class="bi bi-geo-alt-fill" style="color:#2563EB;"></i> You are here</b>' + (objName ? `<br>${objName}` : '')).openPopup();

      const cMarker = L.marker([locLat, locLng], { icon: centerIcon }).addTo(detectMapInstance);
      cMarker.bindPopup(`<b><i class="${assignedMeta.iconClass}" style="color:${assignedMeta.color};"></i> ${locName}</b><br>${assignedMeta.label} &bull; Recommended Center`);

      const allMarkers = [uMarker, cMarker];

      // Plot the other nearby facilities too (smaller, category-colored
      // pins) so the map shows the full picture, not just the assigned one.
      (nearbyLocations || []).forEach(loc => {
        if (!loc || loc.id === assignedLocId || loc.latitude == null || loc.longitude == null) return;
        const meta = getFacilityMarkerMeta(loc.category);
        const icon = makeFacilityDivIcon(meta, 22);
        const marker = L.marker([loc.latitude, loc.longitude], { icon, opacity: 0.85 }).addTo(detectMapInstance);
        const directionsUrl = `https://www.google.com/maps/dir/?api=1&origin=${userLat},${userLng}&destination=${loc.latitude},${loc.longitude}`;
        marker.bindPopup(`<b><i class="${meta.iconClass}" style="color:${meta.color};"></i> ${loc.name}</b><br>${meta.label}${loc.distance_km != null ? ` &bull; ${loc.distance_km} km away` : ''}<br><a href="${directionsUrl}" target="_blank" rel="noopener">Directions</a>`);
        allMarkers.push(marker);
      });

      const group = new L.featureGroup(allMarkers);
      detectMapInstance.fitBounds(group.getBounds().pad(0.25));

      // Draw the route (real road path if available, dashed straight line
      // as a fallback) from the user to the assigned facility.
      drawRouteOrFallback(detectMapInstance, userLat, userLng, locLat, locLng, assignedMeta.color);
    } catch (e) {
      console.error('Tracker map error:', e);
    }
  }

  // Mark completed from detect tracker
  const markCompletedBtn = document.getElementById('markCompletedBtn');
  if (markCompletedBtn) {
    markCompletedBtn.addEventListener('click', async () => {
      if (!currentRequestId) return;
      if (!confirm('Mark this waste item as handed over / completed?')) return;

      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

      try {
        const res = await fetch(`/api/disposal/request/${currentRequestId}/complete`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          }
        });
        const data = await res.json();
        if (res.ok) {
          showStatusAlert('Disposal request marked as completed. Thank you for recycling sustainably!', 'info');
          const stepCompleted = document.getElementById('stepCompleted');
          const progressBar = document.getElementById('stepperProgressBar');
          const statusBadge = document.getElementById('trackerStatusBadge');
          if (stepCompleted) stepCompleted.classList.add('active');
          if (progressBar) progressBar.style.width = 'calc(100% - 80px)';
          if (statusBadge) {
            statusBadge.className = 'badge badge-organic';
            statusBadge.textContent = 'Completed';
          }
          markCompletedBtn.disabled = true;
          markCompletedBtn.textContent = '✓ Completed';
        } else {
          alert(data.error || 'Failed to update status.');
        }
      } catch (err) {
        alert('Network error while completing request.');
      }
    });
  }

  // --- 7. Copy Report Telemetry ---
  if (copyReportBtn) {
    copyReportBtn.addEventListener('click', () => {
      if (!lastPredictionData) return;

      const reportText = `Object: ${lastPredictionData.object || 'N/A'}
Condition: ${lastPredictionData.condition || 'N/A'}
Is Waste: ${lastPredictionData.is_waste ? 'Yes' : 'No'}
Category: ${lastPredictionData.category || lastPredictionData.class || 'N/A'}
Reason: ${lastPredictionData.reason || 'N/A'}`;

      navigator.clipboard.writeText(reportText).then(() => {
        copyReportBtnText.textContent = 'Report Copied!';
        setTimeout(() => {
          copyReportBtnText.textContent = 'Copy AI Telemetry';
        }, 2000);
      }).catch(() => {
        copyReportBtnText.textContent = 'Failed to copy';
      });
    });
  }
});


/* --- Hero reveal on scroll (presentational only) --- */
(function () {
  var items = document.querySelectorAll('.hero-reveal');
  if (!items.length || !('IntersectionObserver' in window)) return;
  items.forEach(function (el) { el.classList.remove('is-visible'); });
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  items.forEach(function (el) { io.observe(el); });
})();
