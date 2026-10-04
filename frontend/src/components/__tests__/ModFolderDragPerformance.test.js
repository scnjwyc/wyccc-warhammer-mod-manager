import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ModList from '../ModList.vue'

describe('folder drag feedback with a large MOD list', () => {
  it('updates insertion feedback without rendering unrelated MOD rows on every hover', async () => {
    let titleReads = 0
    const mods = Array.from({ length: 1000 }, (_, index) => ({
      id: `mod-${index}`, pack_name: `mod-${index}.pack`, source: 'data',
      get effective_name() { titleReads += 1; return `MOD ${index}` },
    }))
    const folders = [
      { id: 'source', name: 'Source', mod_ids: [mods[0].id] },
      { id: 'target', name: 'Target', mod_ids: [mods[1].id] },
    ]
    const wrapper = mount(ModList, { props: {
      title: 'MOD', mods, folders, active: true, orderIds: mods.map(mod => mod.id),
    } })
    try {
      await wrapper.get('[data-testid="mod-folder-source"]').trigger('dragstart')
      const targetFolder = wrapper.get('[data-testid="mod-folder-target"]')
      const rows = wrapper.findAll('.mod-row')
      const targets = [targetFolder, rows[200], rows[400], rows[600]]
      const readsBefore = titleReads
      const durations = []
      for (let index = 0; index < 24; index += 1) {
        const target = targets[index % targets.length]
        const start = performance.now()
        await target.trigger('dragover', { clientY: index % 2 ? -1 : 1 })
        durations.push(performance.now() - start)
        expect(target.classes()).toContain(index % 2 ? 'drop-before' : 'drop-after')
      }
      const readsDuringHover = titleReads - readsBefore
      const ordered = [...durations].sort((a, b) => a - b)
      console.info(JSON.stringify({
        fixture: '1000 MODs / 24 folder dragover events',
        averageMs: Number((durations.reduce((sum, value) => sum + value, 0) / durations.length).toFixed(2)),
        p95Ms: Number(ordered[Math.ceil(ordered.length * 0.95) - 1].toFixed(2)),
        titleReadsDuringHover: readsDuringHover,
      }))
      expect(wrapper.findAll('.mod-row')).toHaveLength(1000)
      expect(readsDuringHover).toBe(0)
      await targetFolder.trigger('drop', { clientY: 1 })
      expect(wrapper.emitted('move-folder')[0][0]).toMatchObject({ folderId: 'source', targetFolderId: 'target' })
      expect(wrapper.emitted('drop-mods')).toBeUndefined()
    } finally {
      wrapper.unmount()
    }
  }, 15000)
})

const mods = ['a', 'b'].map(id => ({ id, effective_name: id, pack_name: `${id}.pack`, source: 'data' }))
const folder = { id: 'folder', name: 'Folder', mod_ids: ['a'] }
const createList = (props = {}) => mount(ModList, { props: { title: 'MOD', mods, folders: [folder], ...props } })

describe('folder drag feedback lifecycle', () => {
  it('avoids redundant DOM updates while hovering in the same position and clears feedback on cancellation', async () => {
    const wrapper = createList()
    const records = []
    const observer = new MutationObserver(changes => records.push(...changes))
    try {
      const source = wrapper.get('[data-testid="mod-folder-folder"]')
      const target = wrapper.findAll('.mod-row')[1]
      const endMarker = wrapper.get('.drop-insertion-marker')
      expect(endMarker.element.hidden).toBe(true)
      await source.trigger('dragstart')
      expect(source.classes()).toContain('dragging')
      await target.trigger('dragover', { clientY: 1 })
      observer.observe(wrapper.get('.mod-list').element, { attributes: true, subtree: true })
      for (let index = 0; index < 20; index += 1) await target.trigger('dragover', { clientY: 1 })
      expect(records).toHaveLength(0)
      observer.disconnect()

      await wrapper.get('.mod-list').trigger('dragover')
      expect(endMarker.element.hidden).toBe(false)
      expect(target.classes()).not.toContain('drop-after')
      await wrapper.get('.mod-list').trigger('dragleave')
      expect(endMarker.element.hidden).toBe(true)
      await target.trigger('dragover', { clientY: -1 })
      await source.trigger('dragend')
      expect(wrapper.findAll('.drop-before, .drop-after, .dragging')).toHaveLength(0)
      expect(endMarker.element.hidden).toBe(true)
      expect(wrapper.emitted('move-folder')).toBeUndefined()
    } finally {
      observer.disconnect()
      wrapper.unmount()
    }
  })

  it('keeps live row updates and insertion feedback correct while dragging', async () => {
    const wrapper = createList({ active: true, orderIds: ['a', 'b'] })
    try {
      const source = wrapper.get('[data-testid="mod-folder-folder"]')
      const target = wrapper.findAll('.mod-row')[1]
      await source.trigger('dragstart')
      await target.trigger('dragover', { clientY: -1 })
      await wrapper.setProps({
        mods: [mods[0], { ...mods[1], effective_name: 'Updated title' }],
        selectedIds: ['b'], orderIds: ['b', 'a'],
      })
      expect(target.get('.row-title').text()).toBe('Updated title')
      expect(target.get('.thumbnail-order').text()).toBe('1')
      expect(target.classes()).toContain('selected')
      expect(target.classes()).toContain('drop-before')
      expect(source.classes()).toContain('dragging')
      await target.trigger('drop', { clientY: 1 })
      expect(wrapper.emitted('move-folder')[0][0]).toMatchObject({
        folderId: 'folder', targetModId: 'b', placement: 'before', listName: 'active',
      })
      expect(wrapper.findAll('.drop-before, .drop-after, .dragging')).toHaveLength(0)
    } finally {
      wrapper.unmount()
    }
  })

  it('clears feedback when a drag from the other panel ends or its target disappears', async () => {
    const wrapper = createList({ dragSource: { kind: 'folder', folderId: 'folder', source: 'active' } })
    try {
      const target = wrapper.findAll('.mod-row')[1]
      await target.trigger('dragover', { clientY: 1 })
      expect(target.classes()).toContain('drop-after')
      await wrapper.setProps({ mods: [mods[0]] })
      expect(wrapper.findAll('.drop-before, .drop-after')).toHaveLength(0)
      await wrapper.get('.mod-list').trigger('dragover')
      expect(wrapper.get('.drop-insertion-marker').element.hidden).toBe(false)
      await wrapper.setProps({ dragSource: null })
      expect(wrapper.get('.drop-insertion-marker').element.hidden).toBe(true)
      expect(wrapper.emitted('move-folder')).toBeUndefined()
    } finally {
      wrapper.unmount()
    }
  })
})
