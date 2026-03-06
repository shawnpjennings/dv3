import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught UI error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen w-screen flex-col items-center justify-center bg-gray-950 text-gray-200 p-8 font-sans">
          <div className="max-w-md w-full bg-gray-900 border border-red-900/50 rounded-lg shadow-2xl overflow-hidden">
            <div className="p-4 bg-red-950/30 border-b border-red-900/30">
              <h1 className="text-lg font-bold text-red-400">Editor Render Error</h1>
            </div>
            <div className="p-6">
              <p className="text-sm text-gray-400 mb-4">
                The application encountered an unexpected error. Your saved data in IndexedDB should still be intact.
              </p>
              <pre className="bg-black/50 p-4 rounded text-xs text-red-300 overflow-x-auto border border-gray-800">
                {this.state.error?.message || 'Unknown Error'}
              </pre>
            </div>
            <div className="p-4 bg-gray-950 border-t border-gray-800 flex justify-end">
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-[#f97316] hover:bg-[#fb923c] text-white rounded text-sm font-medium transition-colors"
              >
                Reload Application
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
