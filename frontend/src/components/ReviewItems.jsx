import React, { useState, useEffect } from 'react';

function normalizeItem(item) {
  return {
    ...item,
    name: item.name != null ? String(item.name).trim() : '',
    quantity: item.quantity != null && item.quantity !== '' ? String(item.quantity) : '',
    unit: item.unit != null ? String(item.unit) : '',
    is_valid: item.is_valid !== false,
  };
}

const ReviewItems = ({ items: initialItems = [], onItemsChange, onValidationChange }) => {
  const normalizedInitial = Array.isArray(initialItems)
    ? initialItems.map(normalizeItem)
    : [];
  const [items, setItems] = useState(() => normalizedInitial);
  const [cutIndex, setCutIndex] = useState(null); // For cut/move functionality

  // When parent sends new items (e.g. after scan), replace state with normalized copy
  useEffect(() => {
    const next = Array.isArray(initialItems) ? initialItems.map(normalizeItem) : [];
    setItems(next);
  }, [initialItems]);

  // Notify parent of changes
  useEffect(() => {
    if (onItemsChange) {
      onItemsChange(items);
    }
    
    // Validate items
    const isValid = items.every(item => item.name && item.name.trim().length > 0);
    if (onValidationChange) {
      onValidationChange(isValid);
    }
  }, [items, onItemsChange, onValidationChange]);

  // Available units for selection
  const units = ['kg', 'g', 'l', 'ml', 'pc'];

  /**
   * Suggests a standardized product name
   * Examples: "Fresh Apples" → "Apple", "Milk (Toned)" → "Milk"
   */
  const suggestName = (originalName) => {
    if (!originalName) return '';
    
    let suggested = originalName.trim();
    
    // Remove common prefixes
    const prefixes = ['fresh', 'organic', 'premium', 'quality', 'best', 'new'];
    prefixes.forEach(prefix => {
      const regex = new RegExp(`^${prefix}\\s+`, 'i');
      suggested = suggested.replace(regex, '');
    });
    
    // Remove text in parentheses (e.g., "Milk (Toned)" → "Milk")
    suggested = suggested.replace(/\s*\([^)]*\)\s*/g, '');
    
    // Remove text in brackets
    suggested = suggested.replace(/\s*\[[^\]]*\]\s*/g, '');
    
    // Capitalize first letter
    if (suggested.length > 0) {
      suggested = suggested.charAt(0).toUpperCase() + suggested.slice(1).toLowerCase();
    }
    
    return suggested.trim();
  };

  // Handle editing item name
  const handleNameChange = (index, newName) => {
    const updatedItems = [...items];
    updatedItems[index].name = newName;
    setItems(updatedItems);
  };

  // Handle accepting suggested name
  const handleAcceptSuggestion = (index) => {
    const updatedItems = [...items];
    const suggested = suggestName(updatedItems[index].name);
    if (suggested) {
      updatedItems[index].name = suggested;
      setItems(updatedItems);
    }
  };

  // Handle editing quantity
  const handleQuantityChange = (index, newQuantity) => {
    const updatedItems = [...items];
    updatedItems[index].quantity = newQuantity;
    setItems(updatedItems);
  };

  // Handle changing unit
  const handleUnitChange = (index, newUnit) => {
    const updatedItems = [...items];
    updatedItems[index].unit = newUnit;
    setItems(updatedItems);
  };

  // Handle removing a row
  const handleRemoveRow = (index) => {
    const updatedItems = items.filter((_, i) => i !== index);
    setItems(updatedItems);
    if (cutIndex === index) {
      setCutIndex(null);
    } else if (cutIndex !== null && cutIndex > index) {
      setCutIndex(cutIndex - 1);
    }
  };

  // Handle adding a new empty row
  const handleAddRow = () => {
    const newItem = {
      name: '',
      quantity: '',
      unit: '',
      is_valid: true
    };
    setItems([...items, newItem]);
  };

  // Handle cutting a row (for moving)
  const handleCutRow = (index) => {
    setCutIndex(index);
  };

  // Handle pasting a row at a specific position
  const handlePasteRow = (targetIndex) => {
    if (cutIndex === null || cutIndex === targetIndex) {
      return;
    }

    const updatedItems = [...items];
    const cutItem = updatedItems[cutIndex];
    
    // Remove from original position
    updatedItems.splice(cutIndex, 1);
    
    // Insert at target position
    const insertIndex = cutIndex < targetIndex ? targetIndex - 1 : targetIndex;
    updatedItems.splice(insertIndex, 0, cutItem);
    
    setItems(updatedItems);
    setCutIndex(null);
  };

  // Handle moving row up
  const handleMoveUp = (index) => {
    if (index === 0) return;
    const updatedItems = [...items];
    [updatedItems[index - 1], updatedItems[index]] = [updatedItems[index], updatedItems[index - 1]];
    setItems(updatedItems);
    if (cutIndex === index) {
      setCutIndex(index - 1);
    } else if (cutIndex === index - 1) {
      setCutIndex(index);
    }
  };

  // Handle moving row down
  const handleMoveDown = (index) => {
    if (index === items.length - 1) return;
    const updatedItems = [...items];
    [updatedItems[index], updatedItems[index + 1]] = [updatedItems[index + 1], updatedItems[index]];
    setItems(updatedItems);
    if (cutIndex === index) {
      setCutIndex(index + 1);
    } else if (cutIndex === index + 1) {
      setCutIndex(index);
    }
  };

  // Check if all items have names
  const allItemsValid = items.every(item => item.name && item.name.trim().length > 0);
  const suggestedName = (index) => {
    const original = items[index].name;
    const suggested = suggestName(original);
    return suggested && suggested !== original ? suggested : null;
  };

  return (
    <div className="review-items stack-lg">
      <div className="review-items-header">
        <h2 className="page-title" style={{ fontSize: '1.1rem', marginBottom: 0 }}>
          Review detected items
        </h2>
        <p className="page-subtitle">
          Check item names, add quantities and units, and remove anything you don&apos;t want to include.
        </p>
      </div>

      {items.length === 0 ? (
        <p className="text-muted">No items to review. Please upload a receipt first.</p>
      ) : (
        <>
          {/* Desktop/tablet: table view */}
          <div className="review-table-wrapper">
            <table className="review-table">
              <thead>
                <tr>
                  <th className="review-th-index">#</th>
                  <th className="review-th-name">Item Name</th>
                  <th className="review-th-qty">Quantity</th>
                  <th className="review-th-unit">Unit</th>
                  <th className="review-th-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const suggestion = suggestedName(index);
                  const isCut = cutIndex === index;
                  return (
                    <tr
                      key={index}
                      className={`review-table-row ${isCut ? 'review-table-row--cut' : ''}`}
                    >
                      <td className="review-td-index">{index + 1}</td>
                      <td className="review-td-name">
                        <div className="stack-md review-name-cell" style={{ marginBottom: 0 }}>
                          <textarea
                            className="input review-name-input"
                            value={item.name}
                            onChange={(e) => handleNameChange(index, e.target.value)}
                            placeholder="Enter item name"
                            rows={1}
                          />
                          {suggestion && (
                            <button
                              type="button"
                              className="btn-icon review-suggestion-btn"
                              onClick={() => handleAcceptSuggestion(index)}
                            >
                              <span>✨</span>
                              <span style={{ fontSize: '0.75rem' }}>Use &quot;{suggestion}&quot;</span>
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="review-td-qty">
                        <input
                          type="number"
                          className="input"
                          value={item.quantity}
                          onChange={(e) => handleQuantityChange(index, e.target.value)}
                          placeholder="Qty"
                          min="0"
                          step="0.01"
                        />
                      </td>
                      <td className="review-td-unit">
                        <select
                          className="input"
                          value={item.unit}
                          onChange={(e) => handleUnitChange(index, e.target.value)}
                        >
                          <option value="">Unit</option>
                          {units.map((unit) => (
                            <option key={unit} value={unit}>
                              {unit}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="review-td-actions">
                        <div className="review-actions">
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={() => handleMoveUp(index)}
                            disabled={index === 0}
                            aria-label="Move item up"
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={() => handleMoveDown(index)}
                            disabled={index === items.length - 1}
                            aria-label="Move item down"
                          >
                            ↓
                          </button>
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={() => handleCutRow(index)}
                            aria-label="Mark item to move"
                          >
                            ✂
                          </button>
                          {cutIndex !== null && cutIndex !== index && (
                            <button
                              type="button"
                              className="btn-icon"
                              onClick={() => handlePasteRow(index)}
                              aria-label="Paste item here"
                            >
                              📌
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn-icon btn-icon-danger"
                            onClick={() => handleRemoveRow(index)}
                            aria-label="Remove item"
                          >
                            🗑
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile: stacked cards */}
          <div className="review-cards">
            {items.map((item, index) => {
              const suggestion = suggestedName(index);
              const isCut = cutIndex === index;
              return (
                <div
                  key={index}
                  className="card card--subtle review-card"
                  style={isCut ? { backgroundColor: '#fefce8' } : undefined}
                >
                  <div className="review-card-row">
                    <div className="review-chip">
                      <span>{index + 1}</span>
                      <span>Item</span>
                    </div>
                    <input
                      className="input review-name-input"
                      value={item.name}
                      onChange={(e) => handleNameChange(index, e.target.value)}
                      placeholder="Enter item name"
                      rows={1}
                    />
                    {suggestion && (
                      <button
                        type="button"
                        className="btn-icon review-suggestion-btn"
                        onClick={() => handleAcceptSuggestion(index)}
                      >
                        <span>✨</span>
                        <span style={{ fontSize: '0.75rem' }}>Use &quot;{suggestion}&quot;</span>
                      </button>
                    )}
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1.3fr 1fr',
                        gap: '0.5rem',
                      }}
                    >
                      <input
                        type="number"
                        className="input"
                        value={item.quantity}
                        onChange={(e) => handleQuantityChange(index, e.target.value)}
                        placeholder="Quantity"
                        min="0"
                        step="0.01"
                      />
                      <select
                        className="input"
                        value={item.unit}
                        onChange={(e) => handleUnitChange(index, e.target.value)}
                      >
                        <option value="">Unit</option>
                        {units.map((unit) => (
                          <option key={unit} value={unit}>
                            {unit}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="review-actions">
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => handleMoveUp(index)}
                        disabled={index === 0}
                        aria-label="Move item up"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => handleMoveDown(index)}
                        disabled={index === items.length - 1}
                        aria-label="Move item down"
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => handleCutRow(index)}
                        aria-label="Mark item to move"
                      >
                        ✂
                      </button>
                      {cutIndex !== null && cutIndex !== index && (
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handlePasteRow(index)}
                          aria-label="Paste item here"
                        >
                          📌
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-icon btn-icon-danger"
                        onClick={() => handleRemoveRow(index)}
                        aria-label="Remove item"
                      >
                        🗑
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button type="button" className="btn btn-secondary" onClick={handleAddRow}>
              ＋ Add item
            </button>
            <span
              className={`review-status ${allItemsValid ? 'valid' : 'invalid'}`}
            >
              {allItemsValid
                ? 'All items look good. You can proceed.'
                : 'Fill in missing names before proceeding.'}
            </span>
          </div>
        </>
      )}
    </div>
  );
};

export default ReviewItems;
