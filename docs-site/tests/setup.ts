// React Testing Library only auto-cleans when a global afterEach exists.
// Without this, renders accumulate across tests and queries find duplicates.
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);
