'use client';

import { Check } from 'lucide-react';

interface Step {
  id: string;
  label: string;
  completed?: boolean;
  active?: boolean;
}

interface ToolStepIndicatorProps {
  steps: Step[];
  currentStep: string;
}

export default function ToolStepIndicator({ steps, currentStep }: ToolStepIndicatorProps) {
  return (
    <div className="flex items-center gap-1 px-2 py-1.5 bg-slate-800/30 rounded-xl">
      {steps.map((step, i) => {
        const isActive = step.id === currentStep;
        const isCompleted = step.completed;
        const isPast = steps.findIndex((s) => s.id === currentStep) > i;

        return (
          <div key={step.id} className="flex items-center">
            {i > 0 && (
              <div className={`w-4 h-px mx-1 ${
                isPast || isCompleted ? 'bg-teal-500' : 'bg-slate-700'
              }`} />
            )}
            <div className="flex items-center gap-1.5">
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium
                ${isCompleted ? 'bg-teal-500 text-white' :
                  isActive ? 'bg-teal-500/20 text-teal-400 ring-1 ring-teal-500' :
                  'bg-slate-700 text-slate-500'}`}
              >
                {isCompleted ? <Check className="w-3 h-3" /> : i + 1}
              </div>
              <span className={`text-xs ${
                isActive ? 'text-teal-400 font-medium' :
                isCompleted ? 'text-slate-400' : 'text-slate-600'
              }`}>
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
