import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SeverityBadge } from '../components/common/SeverityBadge';
import { StatusBadge } from '../components/common/StatusBadge';

describe('SeverityBadge', () => {
  it('renders CRITICAL severity with correct text', () => {
    render(<SeverityBadge severity="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
  });

  it('renders WARNING severity with correct text', () => {
    render(<SeverityBadge severity="WARNING" />);
    expect(screen.getByText('WARNING')).toBeInTheDocument();
  });

  it('renders INFO severity with correct text', () => {
    render(<SeverityBadge severity="INFO" />);
    expect(screen.getByText('INFO')).toBeInTheDocument();
  });
});

describe('StatusBadge', () => {
  it('renders OPEN status badge', () => {
    render(<StatusBadge status="OPEN" />);
    expect(screen.getByText('OPEN')).toBeInTheDocument();
  });

  it('renders INVESTIGATING status badge', () => {
    render(<StatusBadge status="INVESTIGATING" />);
    expect(screen.getByText('INVESTIGATING')).toBeInTheDocument();
  });

  it('renders RESOLVED status badge', () => {
    render(<StatusBadge status="RESOLVED" />);
    expect(screen.getByText('RESOLVED')).toBeInTheDocument();
  });

  it('renders CLOSED status badge', () => {
    render(<StatusBadge status="CLOSED" />);
    expect(screen.getByText('CLOSED')).toBeInTheDocument();
  });
});
