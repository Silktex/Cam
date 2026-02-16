'use client';

import { useEffect } from 'react';
import { X, Keyboard } from 'lucide-react';

interface ShortcutsModalProps {
  open: boolean;
  onClose: () => void;
}

interface Shortcut {
  action: string;
  mac: string;
  win: string;
  scope?: string;
}

const shortcuts: { section: string; items: Shortcut[] }[] = [
  {
    section: 'Navigation',
    items: [
      { action: 'Dashboard', mac: 'D', win: 'D' },
      { action: 'Gallery', mac: 'G', win: 'G' },
      { action: 'Processing', mac: 'P', win: 'P' },
      { action: 'Keyboard Shortcuts', mac: '?', win: '?' },
    ],
  },
  {
    section: 'Dashboard Tabs',
    items: [
      { action: 'Batch Capture', mac: 'B', win: 'B', scope: 'Dashboard' },
      { action: 'Single Capture', mac: 'S', win: 'S', scope: 'Dashboard' },
      { action: 'Color Checker', mac: 'C', win: 'C', scope: 'Dashboard' },
      { action: 'Focus Folder Input', mac: 'F', win: 'F', scope: 'Dashboard' },
      { action: 'Unfocus Input', mac: 'Esc', win: 'Esc', scope: 'Dashboard' },
    ],
  },
  {
    section: 'Lights',
    items: [
      { action: 'Toggle All Lights', mac: 'Space', win: 'Space', scope: 'Dashboard' },
      { action: 'Toggle Top Light', mac: 'T', win: 'T', scope: 'Dashboard' },
      { action: 'Toggle Side 1 Light', mac: '1', win: '1', scope: 'Dashboard' },
      { action: 'Toggle Side 2 Light', mac: '2', win: '2', scope: 'Dashboard' },
      { action: 'Toggle Side 3 Light', mac: '3', win: '3', scope: 'Dashboard' },
      { action: 'Toggle Side 4 Light', mac: '4', win: '4', scope: 'Dashboard' },
      { action: 'Toggle Side 5 Light', mac: '5', win: '5', scope: 'Dashboard' },
      { action: 'Toggle Side 6 Light', mac: '6', win: '6', scope: 'Dashboard' },
      { action: 'Toggle Side 7 Light', mac: '7', win: '7', scope: 'Dashboard' },
      { action: 'Toggle Side 8 Light', mac: '8', win: '8', scope: 'Dashboard' },
    ],
  },
  {
    section: 'Camera',
    items: [
      { action: 'Connect / Disconnect', mac: '\u2318 + C', win: 'Ctrl + C' },
      { action: 'Troubleshoot', mac: '\u2318 + T', win: 'Ctrl + T' },
      { action: 'Start Capture', mac: '\u2318 + S', win: 'Ctrl + S', scope: 'Dashboard' },
      { action: 'Toggle Live View / Settings', mac: 'L', win: 'L', scope: 'Dashboard' },
    ],
  },
  {
    section: 'Gallery Viewer',
    items: [
      { action: 'Previous Image', mac: '\u2190', win: '\u2190', scope: 'Gallery' },
      { action: 'Next Image', mac: '\u2192', win: '\u2192', scope: 'Gallery' },
      { action: 'Zoom In', mac: '+', win: '+', scope: 'Gallery' },
      { action: 'Zoom Out', mac: '-', win: '-', scope: 'Gallery' },
      { action: 'Reset Zoom', mac: '0', win: '0', scope: 'Gallery' },
      { action: 'Close Viewer', mac: 'Esc', win: 'Esc', scope: 'Gallery' },
    ],
  },
  {
    section: 'Crop Editor',
    items: [
      { action: 'Auto Detect Crop', mac: 'A', win: 'A', scope: 'Crop' },
      { action: 'Apply to All Images', mac: '\u2318 + S', win: 'Ctrl + S', scope: 'Crop' },
    ],
  },
];

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[28px] px-1.5 py-0.5 bg-slate-700 border border-slate-600 rounded text-xs font-mono text-slate-200">
      {children}
    </kbd>
  );
}

export default function ShortcutsModal({ open, onClose }: ShortcutsModalProps) {
  useEffect(() => {
    if (!open) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Keyboard className="w-5 h-5 text-teal-400" />
            <h2 className="text-lg font-semibold text-white">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="overflow-y-auto p-6 space-y-6">
          {shortcuts.map((group) => (
            <div key={group.section}>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                {group.section}
              </h3>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-800">
                    <th className="text-left text-xs font-medium text-slate-500 pb-2 pr-4">Action</th>
                    <th className="text-center text-xs font-medium text-slate-500 pb-2 px-4">Mac</th>
                    <th className="text-center text-xs font-medium text-slate-500 pb-2 px-4">Windows / Linux</th>
                    <th className="text-right text-xs font-medium text-slate-500 pb-2 pl-4">Scope</th>
                  </tr>
                </thead>
                <tbody>
                  {group.items.map((shortcut) => (
                    <tr key={shortcut.action} className="border-b border-slate-800/50">
                      <td className="py-2.5 pr-4 text-sm text-slate-200">{shortcut.action}</td>
                      <td className="py-2.5 px-4 text-center">
                        <div className="flex items-center justify-center gap-1">
                          {shortcut.mac.split(' + ').map((k, i) => (
                            <span key={i} className="flex items-center gap-1">
                              {i > 0 && <span className="text-slate-500 text-xs">+</span>}
                              <Kbd>{k.trim()}</Kbd>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <div className="flex items-center justify-center gap-1">
                          {shortcut.win.split(' + ').map((k, i) => (
                            <span key={i} className="flex items-center gap-1">
                              {i > 0 && <span className="text-slate-500 text-xs">+</span>}
                              <Kbd>{k.trim()}</Kbd>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-2.5 pl-4 text-right">
                        {shortcut.scope ? (
                          <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
                            {shortcut.scope}
                          </span>
                        ) : (
                          <span className="text-xs text-teal-500/70 bg-teal-500/10 px-2 py-0.5 rounded-full">
                            Global
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-700 bg-slate-800/30">
          <p className="text-xs text-slate-500 text-center">
            Press <Kbd>?</Kbd> to toggle this panel &middot; Shortcuts are disabled when typing in input fields
          </p>
        </div>
      </div>
    </div>
  );
}
