import { useState } from 'react';
import { IdleScreen } from './components/IdleScreen';
import { ConfirmationScreen } from './components/ConfirmationScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { SuccessScreen } from './components/SuccessScreen';

type ActionType = 'synthesis' | 'reformat' | 'search' | 'respond';
type ScreenState = 
  | { type: 'idle' }
  | { type: 'confirmation'; action: ActionType }
  | { type: 'processing'; action: ActionType }
  | { type: 'success'; action: ActionType };

export default function App() {
  const [screenState, setScreenState] = useState<ScreenState>({ type: 'idle' });

  const handleActionSelect = (action: ActionType) => {
    setScreenState({ type: 'confirmation', action });
  };

  const handleConfirm = () => {
    if (screenState.type === 'confirmation') {
      setScreenState({ type: 'processing', action: screenState.action });
      // Simulate processing time
      setTimeout(() => {
        setScreenState({ type: 'success', action: screenState.action });
      }, 2000);
    }
  };

  const handleCancel = () => {
    setScreenState({ type: 'idle' });
  };

  const handleComplete = () => {
    setScreenState({ type: 'idle' });
  };

  const renderScreen = () => {
    switch (screenState.type) {
      case 'idle':
        return <IdleScreen onActionSelect={handleActionSelect} />;
      case 'confirmation':
        return (
          <ConfirmationScreen
            action={screenState.action}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        );
      case 'processing':
        return <ProcessingScreen action={screenState.action} />;
      case 'success':
        return <SuccessScreen action={screenState.action} onComplete={handleComplete} />;
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 flex items-center justify-center p-8" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
      <div className="flex flex-col items-center gap-8">
        {/* Title */}
        <div className="text-center">
          <h1 className="text-5xl font-bold text-white mb-2 tracking-tight" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
            SPARK UI KIT
          </h1>
          <p className="text-gray-400 text-lg" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
            AI Hardware Device · 320x240 LCD Display
          </p>
        </div>

        {/* Screen Display */}
        <div className="bg-gray-950 p-8 rounded-2xl shadow-2xl border-4 border-gray-700">
          {/* Current State Indicator */}
          <div className="mb-4 text-center">
            <div className="inline-block px-4 py-2 rounded-lg bg-gray-800 border border-gray-700">
              <span className="text-[#7aa2f7] font-semibold text-sm" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
                Current State: {screenState.type.toUpperCase()}
                {screenState.type !== 'idle' && ` → ${screenState.action.toUpperCase()}`}
              </span>
            </div>
          </div>

          {/* LCD Display Frame */}
          <div className="border-8 border-gray-800 rounded-lg shadow-inner">
            {renderScreen()}
          </div>
        </div>

        {/* Specs */}
        <div className="text-center text-gray-500 text-sm max-w-2xl" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
          <div className="grid grid-cols-4 gap-4 mb-4">
            <div className="bg-gray-900/50 p-3 rounded-lg border border-gray-800">
              <div className="text-[#7aa2f7] font-bold mb-1">SYNTHESIS</div>
              <div className="text-white text-xs">Brief 10m</div>
            </div>
            <div className="bg-gray-900/50 p-3 rounded-lg border border-gray-800">
              <div className="text-[#7aa2f7] font-bold mb-1">REFORMAT</div>
              <div className="text-white text-xs">Rewrite Text</div>
            </div>
            <div className="bg-gray-900/50 p-3 rounded-lg border border-gray-800">
              <div className="text-[#7aa2f7] font-bold mb-1">SEARCH</div>
              <div className="text-white text-xs">Find Keywords</div>
            </div>
            <div className="bg-gray-900/50 p-3 rounded-lg border border-gray-800">
              <div className="text-[#7aa2f7] font-bold mb-1">RESPOND</div>
              <div className="text-white text-xs">Draft Reply</div>
            </div>
          </div>
          <p className="text-xs leading-relaxed">
            Interactive flow demonstration · Click any action to see confirmation → processing → success states · 
            Cancel returns to idle screen · Success auto-returns after 2 seconds
          </p>
        </div>
      </div>
    </div>
  );
}