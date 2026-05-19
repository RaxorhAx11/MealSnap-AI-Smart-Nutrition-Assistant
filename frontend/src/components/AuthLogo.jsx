import React from 'react';

export default function AuthLogo() {
  return (
    <div className="auth-logo" aria-label="MealSnap">
      <div className="auth-logo-mark" aria-hidden="true">
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          focusable="false"
          aria-hidden="true"
        >
          <path
            d="M12 2.4c5.3 0 9.6 4.3 9.6 9.6S17.3 21.6 12 21.6 2.4 17.3 2.4 12 6.7 2.4 12 2.4Zm0 2.2a7.4 7.4 0 1 0 0 14.8 7.4 7.4 0 0 0 0-14.8Zm3.95 4.54c.43.28.55.85.27 1.27l-4.4 6.7a.96.96 0 0 1-1.6 0L7.78 13.5a.96.96 0 0 1 .2-1.31.96.96 0 0 1 1.31.2l1.73 2.33 3.66-5.58a.96.96 0 0 1 1.27-.27Z"
            fill="currentColor"
          />
        </svg>
      </div>
      <div className="auth-logo-text">MealSnap</div>
    </div>
  );
}

