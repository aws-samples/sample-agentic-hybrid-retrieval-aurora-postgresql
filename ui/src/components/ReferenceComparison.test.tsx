// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ReferenceComparison } from './ReferenceComparison';

afterEach(cleanup);

it('keeps WANDS labels attached to its own records without invented photos or listing links', () => {
  const { container } = render(<ReferenceComparison ids={['wands-mounts']} />);
  expect(screen.getByRole('heading', { name: '“dual monitor stand”' })).toBeTruthy();
  const single = screen.getByRole('heading', { name: 'Single-screen desk mount' }).closest('article')!;
  const dual = screen.getByRole('heading', { name: 'Two-screen desk mount' }).closest('article')!;
  expect(within(single).getByText('Released label: Partial')).toBeTruthy();
  expect(within(single).getByText('1', { selector: 'dd' })).toBeTruthy();
  expect(within(dual).getByText('Released label: Exact')).toBeTruthy();
  expect(within(dual).getByText('2', { selector: 'dd' })).toBeTruthy();
  expect(container.querySelectorAll('img, a').length).toBe(0);
});

it('distinguishes adjustable arms from an adjustable seat in the chair example', () => {
  render(<ReferenceComparison ids={['wands-chairs']} />);
  const fixed = screen.getByRole('heading', { name: 'Albaugh executive chair' }).closest('article')!;
  expect(within(fixed).getByText('Fixed', { selector: 'dd' })).toBeTruthy();
  expect(within(fixed).getByText('Yes', { selector: 'dd' })).toBeTruthy();
  expect(within(fixed).getByText('The arms are fixed; the seat height is adjustable. Adjustability must name the part that moves.')).toBeTruthy();
});

it.each(['esci-headphones', 'esci-chairs', 'esci-monitors'])('offers a real search for %s without substituting the reviewed cards as results', id => {
  render(<ReferenceComparison ids={[id]} />);
  const href = screen.getByRole('link', { name: 'Try this search →' }).getAttribute('href')!;
  expect(href.startsWith('/catalog?q=')).toBe(true);
  expect(href).toContain('&view=results');
  expect(href).not.toContain('event=');
});
