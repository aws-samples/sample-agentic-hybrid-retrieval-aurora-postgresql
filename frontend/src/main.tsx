import React from 'react';
import ReactDOM from 'react-dom/client';
import WorkbenchApp from './WorkbenchApp';
import './workbench.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <WorkbenchApp />
  </React.StrictMode>,
);
