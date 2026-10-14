import { Suspense } from 'react';

import { SearchPageClient } from '@/components/SearchPageClient';

export const dynamic = 'force-dynamic';

/**
 * Custom adult source entry.
 * Adult source isolation is still enforced server-side by
 * getAvailableApiSites(user, true); this page is intentionally visible
 * because the custom desktop UI exposes it in the sidebar.
 */
export default function UnderPage() {
  return (
    <Suspense>
      <SearchPageClient searchBase='/under' />
    </Suspense>
  );
}
