import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadReceipt } from '../services/api';
import ReviewItems from './ReviewItems';

const ReceiptUpload = () => {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ocrText, setOcrText] = useState([]);
  const [processedItems, setProcessedItems] = useState([]);
  const [reviewedItems, setReviewedItems] = useState([]);
  const [isValid, setIsValid] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  // --- Camera scan flow: preview → capture → crop → use cropped image (same as upload) ---
  const [cameraModalOpen, setCameraModalOpen] = useState(false);
  const [cameraStep, setCameraStep] = useState('preview'); // 'preview' | 'crop'
  const [cameraStream, setCameraStream] = useState(null);
  const [capturedImageData, setCapturedImageData] = useState(null); // data URL for crop step
  const [imageSize, setImageSize] = useState({ w: 1, h: 1 }); // natural size when crop editor loads
  const [crop, setCrop] = useState({ x: 0.05, y: 0.05, w: 0.9, h: 0.9 }); // normalized 0–1
  const [dragState, setDragState] = useState(null); // { kind, startX, startY, startCrop } | null
  const videoRef = useRef(null);
  const cropContainerRef = useRef(null);
  const cropImgRef = useRef(null);

  /**
   * Removes unwanted text patterns from receipt (payment methods, thank you messages, etc.)
   */
  const removeUnwantedText = (text) => {
    const unwantedPatterns = [
      /payment\s+method:?\s*/gi,
      /thank\s+you\s+for\s+shopping/gi,
      /thank\s+you/gi,
      /transaction\s+id:?\s*\d+/gi,
      /invoice\s+no:?\s*\d+/gi,
      /date:?\s*\d+/gi,
      /time:?\s*\d+/gi,
      /total:?\s*\d+/gi,
      /subtotal:?\s*\d+/gi,
      /tax:?\s*\d+/gi,
      /discount:?\s*\d+/gi,
      /cash:?\s*\d+/gi,
      /change:?\s*\d+/gi,
      /card\s+payment/gi,
      /upi\s+payment/gi,
      /visa|mastercard|amex/gi,
      /store\s+slogan|visit\s+us|follow\s+us/gi,
    ];
    
    let cleaned = text;
    unwantedPatterns.forEach(pattern => {
      cleaned = cleaned.replace(pattern, '');
    });
    
    return cleaned;
  };

  /**
   * Checks if a line is likely a quantity-only line (e.g., "1kg", "200g")
   */
  const isQuantityOnly = (line) => {
    const quantityPattern = /^\s*\d+\.?\d*\s*(kg|g|l|ml|pc|pcs|pieces?)\s*$/i;
    return quantityPattern.test(line.trim());
  };

  /**
   * Post-processes OCR text to extract item phrases and remove quantities
   * @param {string[]} rawOcrText - Array of raw OCR text lines
   * @returns {Array} Array of item objects with name, quantity, unit, is_valid
   */
  const processOcrText = (rawOcrText) => {
    if (!rawOcrText || rawOcrText.length === 0) {
      return [];
    }

    // Combine all OCR text into a single string, then split by newlines
    const combinedText = Array.isArray(rawOcrText) 
      ? rawOcrText.join('\n') 
      : String(rawOcrText);
    
    // Remove unwanted text first
    let cleanedText = removeUnwantedText(combinedText);
    
    // Split into lines and filter out empty lines
    const lines = cleanedText
      .split(/\n+/)
      .map(line => line.trim())
      .filter(line => line.length > 0);

    const items = [];
    let i = 0;

    while (i < lines.length) {
      const currentLine = lines[i];
      const nextLine = i + 1 < lines.length ? lines[i + 1] : null;

      // Skip if it's a quantity-only line (will be handled by previous item if needed)
      if (isQuantityOnly(currentLine)) {
        i++;
        continue;
      }

      // Check if next line is a quantity-only line
      if (nextLine && isQuantityOnly(nextLine)) {
        // Current line is item name, next line is quantity - skip quantity
        let itemName = currentLine;
        
        // Remove any quantity patterns that might still be in the name
        const quantityPattern = /\d+\.?\d*\s*(kg|g|l|ml|pc|pcs|pieces?)\s*/gi;
        itemName = itemName.replace(quantityPattern, '').trim();
        
        // Remove prices at the end
        itemName = itemName.replace(/\s+\d+\.?\d*\s*$/, '').trim();
        
        if (itemName.length >= 2 && !/^[\d\s\.\-\$€£]+$/.test(itemName)) {
          items.push({
            name: itemName,
            quantity: '',
            unit: '',
            is_valid: true
          });
        }
        i += 2; // Skip both lines
      } else {
        // Regular line - extract item name
        let itemName = currentLine;
        
        // Remove quantity patterns from the line
        const quantityPattern = /\d+\.?\d*\s*(kg|g|l|ml|pc|pcs|pieces?)\s*/gi;
        itemName = itemName.replace(quantityPattern, '').trim();
        
        // Remove prices at the end
        itemName = itemName.replace(/\s+\d+\.?\d*\s*$/, '').trim();
        
        // Skip if too short or only numbers/special chars
        if (itemName.length >= 2 && !/^[\d\s\.\-\$€£]+$/.test(itemName)) {
          items.push({
            name: itemName,
            quantity: '',
            unit: '',
            is_valid: true
          });
        }
        i++;
      }
    }

    return items;
  };

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      // Validate file type
      const validTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!validTypes.includes(selectedFile.type)) {
        setError('Please select a valid image file (JPG or PNG)');
        setFile(null);
        return;
      }
      setFile(selectedFile);
      setError(null);
      setSuccess(false);
      setOcrText([]);
      setProcessedItems([]);
      setReviewedItems([]);
      setIsValid(false);
    }
  };

  // Stop camera stream and reset modal. Used when closing or before moving to crop.
  const stopCamera = useCallback(() => {
    if (cameraStream) {
      cameraStream.getTracks().forEach((t) => t.stop());
      setCameraStream(null);
    }
    if (videoRef.current) videoRef.current.srcObject = null;
  }, [cameraStream]);

  // Open camera modal: request getUserMedia (environment = rear on mobile; fallback to any camera on desktop). Instructions in overlay; hidden after capture.
  const openCameraModal = async () => {
    setError(null);
    try {
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      } catch {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      setCameraStream(stream);
      setCameraModalOpen(true);
      setCameraStep('preview');
      setCapturedImageData(null);
      setCrop({ x: 0.05, y: 0.05, w: 0.9, h: 0.9 });
    } catch (err) {
      setError(err.message || 'Camera access is needed to scan.');
    }
  };

  // Attach stream to video when available.
  useEffect(() => {
    if (!cameraStream || !videoRef.current) return;
    videoRef.current.srcObject = cameraStream;
    return () => { videoRef.current && (videoRef.current.srcObject = null); };
  }, [cameraStream]);

  // Capture current video frame, stop stream, switch to crop step. Instructions are hidden in crop.
  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video || !cameraStream) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    stopCamera();
    setCameraStream(null);
    setCapturedImageData(dataUrl);
    setCameraStep('crop');
    setCrop({ x: 0.05, y: 0.05, w: 0.9, h: 0.9 });
  };

  // Close camera/crop modal: stop stream if any, clear captured image.
  const closeCameraModal = () => {
    stopCamera();
    setCameraModalOpen(false);
    setCameraStep('preview');
    setCapturedImageData(null);
    setDragState(null);
  };

  // Crop editor: store natural size when image loads (for aspect-ratio and canvas crop).
  const onCropImageLoad = (e) => {
    const { naturalWidth: w, naturalHeight: h } = e.target;
    setImageSize({ w, h });
  };

  // Clamp crop so it stays inside [0,1] and has min size. Used after move/resize.
  const clampCrop = (c) => {
    const min = 0.08;
    let { x, y, w, h } = c;
    if (w < min) w = min;
    if (h < min) h = min;
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > 1) w = 1 - x;
    if (y + h > 1) h = 1 - y;
    if (w < min) { w = min; x = Math.max(0, 1 - w); }
    if (h < min) { h = min; y = Math.max(0, 1 - h); }
    return { x, y, w, h };
  };

  // Convert client position to normalized (0–1) relative to crop container.
  const clientToNorm = (clientX, clientY) => {
    const el = cropContainerRef.current;
    if (!el) return { x: 0, y: 0 };
    const r = el.getBoundingClientRect();
    return {
      x: (clientX - r.left) / r.width,
      y: (clientY - r.top) / r.height,
    };
  };

  const handleCropPointerDown = (e, kind) => {
    e.preventDefault();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    setDragState({ kind, startX: clientX, startY: clientY, startCrop: { ...crop } });
  };

  useEffect(() => {
    if (!dragState) return;
    const onMove = (e) => {
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      const { kind, startX, startY, startCrop } = dragState;
      const p = clientToNorm(clientX, clientY);
      const p0 = clientToNorm(startX, startY);
      const dx = p.x - p0.x, dy = p.y - p0.y;
      let next = { ...startCrop };
      if (kind === 'move') {
        next.x = startCrop.x + dx;
        next.y = startCrop.y + dy;
      } else if (kind === 'nw') {
        next.x = p.x; next.y = p.y;
        next.w = (startCrop.x + startCrop.w) - p.x; next.h = (startCrop.y + startCrop.h) - p.y;
      } else if (kind === 'ne') {
        next.y = p.y; next.w = p.x - startCrop.x; next.h = (startCrop.y + startCrop.h) - p.y;
      } else if (kind === 'sw') {
        next.x = p.x; next.w = (startCrop.x + startCrop.w) - p.x; next.h = p.y - startCrop.y;
      } else if (kind === 'se') {
        next.w = p.x - startCrop.x; next.h = p.y - startCrop.y;
      }
      setCrop(clampCrop(next));
    };
    const onUp = () => setDragState(null);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('touchend', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('touchend', onUp);
    };
  }, [dragState]);

  // Close modal on Escape.
  useEffect(() => {
    if (!cameraModalOpen) return;
    const onKey = (e) => { if (e.key === 'Escape') closeCameraModal(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cameraModalOpen]);

  // Apply crop: draw the selected region to canvas, export as File, feed into existing upload flow.
  const applyCrop = () => {
    const img = cropImgRef.current;
    if (!img || !capturedImageData) return;
    const { w: iw, h: ih } = imageSize;
    const { x, y, w, h } = crop;
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(iw * w));
    c.height = Math.max(1, Math.round(ih * h));
    const ctx = c.getContext('2d');
    ctx.drawImage(img, iw * x, ih * y, iw * w, ih * h, 0, 0, c.width, c.height);
    c.toBlob(
      (blob) => {
        const f = new File([blob], 'receipt.jpg', { type: 'image/jpeg' });
        setFile(f);
        setError(null);
        setSuccess(false);
        setOcrText([]);
        setProcessedItems([]);
        setReviewedItems([]);
        setIsValid(false);
        closeCameraModal();
      },
      'image/jpeg',
      0.92
    );
  };

  // Re-capture: go back to preview, clear captured image, re-request camera.
  const recapturePhoto = () => {
    setCapturedImageData(null);
    setCameraStep('preview');
    setDragState(null);
    openCameraModal();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!file) {
      setError('Please select a file first');
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(false);
    setOcrText([]);
    setProcessedItems([]);
    setReviewedItems([]);
    setIsValid(false);

    try {
      const response = await uploadReceipt(file);
      const rawText = response.raw_ocr_text || [];
      setOcrText(rawText);
      
      // Process OCR text to extract items
      const items = processOcrText(rawText);
      setProcessedItems(items);
      
      setSuccess(true);
    } catch (err) {
      setError(err.message || 'Failed to upload and process receipt');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card" style={{ maxWidth: 580 }}>
        <div className="auth-card-header">
          <h1 className="auth-card-title">Upload receipt</h1>
          <p className="auth-card-subtitle">
            Upload a clear photo of your grocery receipt. We&apos;ll detect items and prepare them for review.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="stack-md">
          {/* Two input methods: device file picker and camera. Both use the same handleFileChange and upload API. */}
          <div className="receipt-options">
            {/* Upload from Device: opens file picker (gallery on mobile, file system on desktop). */}
            <div className="receipt-option">
              <div className="receipt-option-icon">📁</div>
              <h3 className="receipt-option-title">Upload Receipt from Device</h3>
              <p className="receipt-option-desc">Choose an image (JPG or PNG) from your device.</p>
              <label
                htmlFor="file-input"
                className="btn btn-secondary receipt-option-btn"
                style={{ cursor: loading ? 'default' : 'pointer' }}
              >
                Choose file
              </label>
              <input
                id="file-input"
                type="file"
                accept="image/jpeg,image/jpg,image/png"
                onChange={handleFileChange}
                disabled={loading}
                style={{ display: 'none' }}
              />
            </div>

            {/* Scan with Camera: opens custom modal with live preview, instructions, then crop. Cropped image goes to same upload API. */}
            <div className="receipt-option receipt-option--camera">
              <div className="receipt-option-icon">📷</div>
              <h3 className="receipt-option-title">Scan Receipt using Camera</h3>
              <p className="receipt-option-desc">Take a photo, then crop to the receipt.</p>
              <button
                type="button"
                className="btn btn-secondary receipt-option-btn"
                onClick={openCameraModal}
                disabled={loading}
              >
                Open camera
              </button>
            </div>
          </div>

          {/* Camera modal: live preview with instructions and focus overlay, then crop with confirm/re-capture. */}
          {cameraModalOpen && (
            <div className="camera-modal" role="dialog" aria-modal="true" aria-label="Scan receipt">
              <button type="button" className="camera-modal-close" onClick={closeCameraModal} aria-label="Close">
                ×
              </button>

              {cameraStep === 'preview' && (
                <div className="camera-preview-wrap">
                  <video ref={videoRef} autoPlay playsInline muted className="camera-preview-video" />
                  {/* Focus overlay: dark edges to guide alignment; instructions on top. Hidden after capture. */}
                  <div className="camera-preview-overlay">
                    <div className="camera-instructions">
                      <span>Align the receipt inside the frame</span>
                      <span>Ensure good lighting</span>
                      <span>Avoid shadows and blur</span>
                    </div>
                    <div className="camera-focus-shade camera-focus-shade-t" />
                    <div className="camera-focus-shade camera-focus-shade-b" />
                    <div className="camera-focus-shade camera-focus-shade-l" />
                    <div className="camera-focus-shade camera-focus-shade-r" />
                    <div className="camera-focus-frame" aria-hidden="true" />
                    <button type="button" className="btn btn-primary camera-capture-btn" onClick={capturePhoto}>
                      Capture
                    </button>
                  </div>
                </div>
              )}

              {cameraStep === 'crop' && capturedImageData && (
                <div className="camera-crop-wrap">
                  <div
                    ref={cropContainerRef}
                    className="crop-editor"
                    style={{ aspectRatio: imageSize.w && imageSize.h ? `${imageSize.w} / ${imageSize.h}` : '4/3' }}
                  >
                    <img
                      ref={cropImgRef}
                      src={capturedImageData}
                      alt="Captured receipt"
                      onLoad={onCropImageLoad}
                    />
                    {/* Shade outside crop area; crop frame has draggable corners to resize, drag body to move. */}
                    <div className="crop-shade crop-shade-t" style={{ height: `${crop.y * 100}%` }} />
                    <div className="crop-shade crop-shade-b" style={{ top: `${(crop.y + crop.h) * 100}%`, height: `${(1 - crop.y - crop.h) * 100}%` }} />
                    <div className="crop-shade crop-shade-l" style={{ top: `${crop.y * 100}%`, left: 0, width: `${crop.x * 100}%`, height: `${crop.h * 100}%` }} />
                    <div className="crop-shade crop-shade-r" style={{ top: `${crop.y * 100}%`, right: 0, width: `${(1 - crop.x - crop.w) * 100}%`, height: `${crop.h * 100}%` }} />
                    <div
                      className="crop-frame"
                      style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%` }}
                    >
                      <span className="crop-handle crop-handle-nw" onMouseDown={(e) => handleCropPointerDown(e, 'nw')} onTouchStart={(e) => handleCropPointerDown(e, 'nw')} />
                      <span className="crop-handle crop-handle-ne" onMouseDown={(e) => handleCropPointerDown(e, 'ne')} onTouchStart={(e) => handleCropPointerDown(e, 'ne')} />
                      <span className="crop-handle crop-handle-sw" onMouseDown={(e) => handleCropPointerDown(e, 'sw')} onTouchStart={(e) => handleCropPointerDown(e, 'sw')} />
                      <span className="crop-handle crop-handle-se" onMouseDown={(e) => handleCropPointerDown(e, 'se')} onTouchStart={(e) => handleCropPointerDown(e, 'se')} />
                      <div className="crop-frame-body" onMouseDown={(e) => handleCropPointerDown(e, 'move')} onTouchStart={(e) => handleCropPointerDown(e, 'move')} />
                    </div>
                  </div>
                  <div className="camera-crop-actions">
                    <button type="button" className="btn btn-secondary" onClick={recapturePhoto}>Re-capture</button>
                    <button type="button" className="btn btn-primary" onClick={applyCrop}>Use this crop</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {file && (
            <p className="text-muted" style={{ fontSize: '0.85rem' }}>
              Selected: <span style={{ fontWeight: 500 }}>{file.name}</span>
            </p>
          )}

          <button type="submit" className="btn btn-primary" disabled={loading || !file}>
            {loading ? 'Uploading & processing…' : 'Upload and analyze'}
          </button>

          {error && <div className="form-error">{error}</div>}
        </form>

        {success && processedItems.length > 0 && (
          <div style={{ marginTop: 'var(--space-4)' }} className="stack-md">
            <ReviewItems
              items={processedItems}
              onItemsChange={(items) => setReviewedItems(items)}
              onValidationChange={(valid) => setIsValid(valid)}
            />

            {isValid && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  navigate('/upload/next', { state: { items: reviewedItems } });
                }}
              >
                Proceed to next step
              </button>
            )}
          </div>
        )}

        {success && processedItems.length === 0 && (
          <p className="text-muted" style={{ marginTop: 'var(--space-4)' }}>
            No items were detected in this receipt. Try another image with clearer text.
          </p>
        )}
      </div>
    </div>
  );
};

export default ReceiptUpload;
