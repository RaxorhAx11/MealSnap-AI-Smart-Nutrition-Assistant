const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

/** JWT key in localStorage; must match backend / Login / ProtectedRoute. */
const TOKEN_KEY = 'jwt_token';

/** Headers for protected APIs. User-based isolation: backend scopes data by user ID; never shared between users. */
function authHeaders() {
  const t = localStorage.getItem(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const errorData = await response
      .json()
      .catch(() => ({ detail: 'Unknown error occurred' }));
    const detail =
      typeof errorData?.detail === 'string'
        ? errorData.detail
        : errorData?.detail
          ? JSON.stringify(errorData.detail)
          : null;
    throw new Error(detail || `HTTP error! status: ${response.status}`);
  }
  return await response.json();
}

/**
 * Create a new user account.
 * @param {Object} payload - { username, email, password }
 * @returns {Promise<Object>} { message }
 */
export const signup = async ({ username, email, password }) => {
  return await fetchJson(`${API_BASE_URL}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  });
};

/**
 * Log in with username or email and password.
 * @param {Object} payload - { username_or_email, password }
 * @returns {Promise<Object>} { access_token, token_type, expires_in, user }
 */
export const login = async ({ username_or_email, password }) => {
  return await fetchJson(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username_or_email, password }),
  });
};

/**
 * Upload receipt image to backend and get OCR extracted text.
 * Requires auth; receipts stored per user and never shared.
 * @param {File} file - Image file to upload
 * @returns {Promise<Object>} Response from API with OCR text
 */
export const uploadReceipt = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return await fetchJson(`${API_BASE_URL}/upload-receipt`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: formData,
  });
};

/**
 * Generate a weekly meal plan from backend
 * 
 * IMPROVED: Items are now automatically fetched from the backend database
 * (from confirmed items stored during nutrition analysis).
 * 
 * @param {Object} [options] - Optional configuration
 *   - items: Optional array of items to use (if not provided, backend fetches latest confirmed items)
 * @returns {Promise<Object>} Response from API with meal plan
 */
export const generateMealPlan = async (options = {}) => {
  // Build request body - items are optional, backend will auto-fetch if not provided
  const body = {};
  if (options.items && Array.isArray(options.items) && options.items.length > 0) {
    // Convert items to the format expected by backend
    body.items = options.items.map(item => 
      typeof item === 'string' ? { name: item } : item
    );
  }
  
  return await fetchJson(`${API_BASE_URL}/generate-meal-plan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify(body),
  });
};

/**
 * Fetch dashboard data (weight + nutrition history). User-scoped; never shared.
 */
export const fetchDashboardData = async ({ days = 30 } = {}) => {
  const q = new URLSearchParams();
  if (days != null) q.set('days', String(days));
  const opts = { headers: { ...authHeaders() } };
  const primary = `${API_BASE_URL}/dashboard?${q.toString()}`;
  try {
    return await fetchJson(primary, opts);
  } catch (e) {
    const fallback = `${API_BASE_URL}/dashboard-data?${q.toString()}`;
    return await fetchJson(fallback, opts);
  }
};

export const fetchWeightHistory = async ({ startDate, endDate } = {}) => {
  const q = new URLSearchParams();
  if (startDate) q.set('start_date', startDate);
  if (endDate) q.set('end_date', endDate);
  const suffix = q.toString() ? `?${q.toString()}` : '';
  return await fetchJson(`${API_BASE_URL}/weights${suffix}`, { headers: { ...authHeaders() } });
};

export const saveWeight = async ({ date, weight }) => {
  return await fetchJson(`${API_BASE_URL}/weights`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ date, weight }),
  });
};

/**
 * Analyze nutrition for a list of items
 * @param {Array} items - Array of items with name, quantity, unit
 * @returns {Promise<Object>} Response from API with nutrition analysis and summary
 */
export const analyzeNutrition = async (items) => {
  // Validate and clean items before sending
  // Backend expects quantity to be a float, not an empty string
  const cleanedItems = items
    .filter(item => {
      // Filter out items without a name
      if (!item.name || !item.name.trim()) {
        return false;
      }
      // Filter out items without a valid quantity
      if (!item.quantity || item.quantity === '' || item.quantity === null || item.quantity === undefined) {
        return false;
      }
      // Filter out items without a unit
      if (!item.unit || item.unit.trim() === '') {
        return false;
      }
      return true;
    })
    .map(item => {
      // Convert quantity to number (handle string numbers)
      let quantity = item.quantity;
      if (typeof quantity === 'string') {
        quantity = quantity.trim();
        // Try to parse as float
        const parsed = parseFloat(quantity);
        if (isNaN(parsed)) {
          return null; // Invalid quantity, will be filtered out
        }
        quantity = parsed;
      } else if (typeof quantity !== 'number') {
        return null; // Invalid type, will be filtered out
      }
      
      return {
        name: item.name.trim(),
        quantity: quantity,
        unit: item.unit.trim()
      };
    })
    .filter(item => item !== null); // Remove any null items from invalid conversions

  if (cleanedItems.length === 0) {
    throw new Error('No valid items to analyze. Please ensure all items have a name, quantity, and unit.');
  }

  return await fetchJson(`${API_BASE_URL}/analyze-nutrition`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ items: cleanedItems }),
  });
};

/**
 * Fetch the latest nutrition summary from the database. User-scoped; never shared.
 * @returns {Promise<Object>} Response with date, calories, protein, carbs, fats
 */
export const fetchDashboardNutrition = async () => {
  return await fetchJson(`${API_BASE_URL}/dashboard-nutrition`, { headers: { ...authHeaders() } });
};

/**
 * Fetch purchase suggestions based on stored nutrition summary. User-scoped; never shared.
 * @returns {Promise<Object>} Response with message and suggestions array
 */
export const fetchPurchaseSuggestions = async () => {
  return await fetchJson(`${API_BASE_URL}/next-purchase-suggestions`, { headers: { ...authHeaders() } });
};
