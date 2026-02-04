import { describe, expect, it, vi } from 'bun:test';
import { getTooltipText } from './alpine-tooltip';

describe('getTooltipText', () => {
  it('returns empty string for empty expression', () => {
    const mockEvaluate = vi.fn();
    expect(getTooltipText('', mockEvaluate)).toBe('');
    expect(mockEvaluate).not.toHaveBeenCalled();
  });

  it('evaluates expression when evaluate succeeds', () => {
    const mockEvaluate = vi.fn().mockReturnValue('Evaluated tooltip');
    const result = getTooltipText('someVar', mockEvaluate);
    expect(result).toBe('Evaluated tooltip');
    expect(mockEvaluate).toHaveBeenCalledWith('someVar');
  });

  it('parses single-quoted string literal when evaluate fails', () => {
    const mockEvaluate = vi.fn().mockImplementation(() => {
      throw new Error('No x-data context');
    });
    const result = getTooltipText("'Hello World'", mockEvaluate);
    expect(result).toBe('Hello World');
  });

  it('parses double-quoted string literal when evaluate fails', () => {
    const mockEvaluate = vi.fn().mockImplementation(() => {
      throw new Error('No x-data context');
    });
    const result = getTooltipText('"Hello World"', mockEvaluate);
    expect(result).toBe('Hello World');
  });

  it('parses single-quoted string literal when evaluate returns empty', () => {
    const mockEvaluate = vi.fn().mockReturnValue('');
    const result = getTooltipText("'Tooltip text'", mockEvaluate);
    expect(result).toBe('Tooltip text');
  });

  it('falls back to plain text when evaluate fails and no quotes', () => {
    const mockEvaluate = vi.fn().mockImplementation(() => {
      throw new Error('No x-data context');
    });
    const result = getTooltipText('Plain text tooltip', mockEvaluate);
    expect(result).toBe('Plain text tooltip');
  });

  it('handles whitespace around quoted strings', () => {
    const mockEvaluate = vi.fn().mockImplementation(() => {
      throw new Error('No x-data context');
    });
    const result = getTooltipText("  'Trimmed tooltip'  ", mockEvaluate);
    expect(result).toBe('Trimmed tooltip');
  });

  it('handles template expression from Jinja2', () => {
    const mockEvaluate = vi.fn().mockImplementation(() => {
      throw new Error('No x-data context');
    });
    const result = getTooltipText("'Workspace settings'", mockEvaluate);
    expect(result).toBe('Workspace settings');
  });
});
