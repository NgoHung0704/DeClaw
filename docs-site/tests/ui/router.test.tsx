/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { RouterProvider, useNavigate, useRoute } from '../../src/router/Router';

function Harness() {
  const route = useRoute();
  const navigate = useNavigate();
  const depth = route.segments.length;
  return (
    <div>
      <span data-testid="hash">{route.segments.join('/')}</span>
      <button
        data-testid="trigger"
        data-route-target="edge"
        onClick={() => navigate({ segments: ['map', 'edge', 'e1'], query: {} })}
      />
      {depth >= 3 && (
        <div data-panel-heading tabIndex={-1} data-testid="panel">
          <button
            data-testid="trigger2"
            data-route-target="fn"
            onClick={() => navigate({ segments: ['map', 'edge', 'e1', 'fn', 'f1'], query: {} })}
          />
        </div>
      )}
      {depth >= 5 && <div data-panel-heading tabIndex={-1} data-testid="panel2" />}
    </div>
  );
}

const renderApp = () =>
  render(
    <RouterProvider>
      <Harness />
    </RouterProvider>,
  );

beforeEach(() => {
  window.location.hash = '#/map';
});

describe('Escape closes exactly one layer', () => {
  it('pops one panel per press, not the whole stack', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getByTestId('trigger'));
    await user.click(screen.getByTestId('trigger2'));
    expect(screen.getByTestId('hash').textContent).toBe('map/edge/e1/fn/f1');

    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map/edge/e1');

    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map');
  });

  it('does nothing at a top-level view', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map');
  });
});

describe('focus', () => {
  it('moves focus into an opened panel', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getByTestId('trigger'));
    expect(document.activeElement).toBe(screen.getByTestId('panel'));
  });

  it('returns focus to the trigger when Escape closes the panel', async () => {
    const user = userEvent.setup();
    renderApp();
    const trigger = screen.getByTestId('trigger');
    await user.click(trigger);
    await user.keyboard('{Escape}');
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(document.activeElement).toBe(trigger);
  });
});
