import { shallowRef } from 'vue'
import { api } from './session'

export type SiteBranding = {
  title: string
  portrait: string | null
  background: string | null
}

export const branding = shallowRef<SiteBranding>({
  title: 'Minecraft Panel',
  portrait: null,
  background: null,
})

export function applyBranding(settings: SiteBranding) {
  branding.value = settings
  document.title = settings.title
}

export async function loadBranding() {
  applyBranding(await api<SiteBranding>('/site', { signal: AbortSignal.timeout(4000) }))
}
