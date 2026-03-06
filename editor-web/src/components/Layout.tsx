import * as React from 'react';
import { Layers } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className="flex h-screen w-screen flex-col bg-gray-950 text-gray-200 overflow-hidden font-sans">
      <header className="flex items-center p-4 border-b border-gray-800 bg-gray-900 shrink-0">
        <Layers className="w-6 h-6 mr-3 text-indigo-500" />
        <h1 className="text-xl font-bold tracking-wide">WebPew</h1>
      </header>
      <main className="flex-1 overflow-hidden relative">
        {children}
      </main>
    </div>
  );
};
