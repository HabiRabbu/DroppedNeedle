import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ contributionId: params.id });
