import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WorkspacesPage } from '../pages/WorkspacesPage';

// Mock workspaces API
vi.mock('../api/workspaces', () => ({
  listWorkspaces: vi.fn().mockResolvedValue({
    items: [
      {
        id: 'ws-123',
        name: 'SRE Production Core',
        created_by: 'user-1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        member_count: 3,
        current_user_role: 'admin',
      },
    ],
    total: 1,
  }),
  createWorkspace: vi.fn(),
  listWorkspaceMembers: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));

describe('WorkspacesPage', () => {
  it('renders team workspaces header and action button', async () => {
    render(<WorkspacesPage />);

    expect(screen.getByRole('heading', { name: /Team Workspaces/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /New Workspace/i })).toBeInTheDocument();
  });

  it('renders workspace card with role badge after loading', async () => {
    render(<WorkspacesPage />);

    expect(await screen.findByText('SRE Production Core')).toBeInTheDocument();
    expect(screen.getByText('ADMIN')).toBeInTheDocument();
  });
});
