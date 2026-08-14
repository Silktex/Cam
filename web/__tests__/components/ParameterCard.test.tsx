import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ParameterCard, {
  SliderControl,
  ToggleControl,
  SelectControl,
} from '@/app/processing/tools/components/ParameterCard';

describe('ParameterCard', () => {
  it('PC-01: renders title and description', () => {
    render(
      <ParameterCard title="Brightness" description="Adjust the brightness level">
        <div>controls</div>
      </ParameterCard>
    );
    expect(screen.getByText('Brightness')).toBeDefined();
    expect(screen.getByText('Adjust the brightness level')).toBeDefined();
  });

  it('PC-02: children rendered when not collapsed', () => {
    render(
      <ParameterCard title="Test" collapsed={false}>
        <div>Child Content</div>
      </ParameterCard>
    );
    expect(screen.getByText('Child Content')).toBeDefined();
  });

  it('PC-03: children hidden when collapsed=true', () => {
    render(
      <ParameterCard title="Test" collapsed={true}>
        <div>Child Content</div>
      </ParameterCard>
    );
    expect(screen.queryByText('Child Content')).toBeNull();
  });
});

describe('SliderControl', () => {
  it('PC-04: fires onChange with parsed float value', () => {
    const onChange = vi.fn();
    render(
      <SliderControl label="Amount" value={0.5} min={0} max={1} step={0.1} onChange={onChange} />
    );
    const slider = screen.getByRole('slider');
    fireEvent.change(slider, { target: { value: '0.8' } });
    expect(onChange).toHaveBeenCalledWith(0.8);
  });

  it('PC-05: shows formatted value with unit suffix', () => {
    render(
      <SliderControl label="Amount" value={50} min={0} max={100} step={1} unit="%" onChange={() => {}} />
    );
    expect(screen.getByText('50%')).toBeDefined();
  });
});

describe('ToggleControl', () => {
  it('PC-06: toggles value on click', () => {
    const onChange = vi.fn();
    render(<ToggleControl label="Enable" value={false} onChange={onChange} />);
    const button = screen.getByRole('button');
    fireEvent.click(button);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe('SelectControl', () => {
  const options = [
    { value: 'linear', label: 'Linear' },
    { value: 'srgb', label: 'sRGB' },
    { value: 'rec709', label: 'Rec.709' },
  ];

  it('PC-07: renders all options', () => {
    render(
      <SelectControl label="Color Space" value="linear" options={options} onChange={() => {}} />
    );
    expect(screen.getByText('Linear')).toBeDefined();
    expect(screen.getByText('sRGB')).toBeDefined();
    expect(screen.getByText('Rec.709')).toBeDefined();
  });

  it('PC-08: fires onChange with selected value', () => {
    const onChange = vi.fn();
    render(
      <SelectControl label="Color Space" value="linear" options={options} onChange={onChange} />
    );
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'srgb' } });
    expect(onChange).toHaveBeenCalledWith('srgb');
  });
});
