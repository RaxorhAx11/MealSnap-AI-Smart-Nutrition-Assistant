import React from 'react';

export default function Layout({ children }) {
  return (
    <div className="app-root">
      <div className="app-shell">
        {children}
      </div>
    </div>
  );
}

