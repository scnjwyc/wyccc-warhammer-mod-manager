import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SaveGamesModal from '../SaveGamesModal.vue'

describe('SaveGamesModal', () => {
  it('sort-preserving list can be filtered and loads the selected save', async () => {
    const wrapper = mount(SaveGamesModal, {
      props: {
        open: true,
        directory: 'C:/Users/Test/AppData/Roaming/The Creative Assembly/Warhammer3/save_games',
        saves: [
          { name: '赵明.save', path: 'one', modified_at: 2_000, size: 2048 },
          { name: '震旦.save', path: 'two', modified_at: 1_000, size: 4096 },
        ],
      },
    })

    await wrapper.get('input[type="search"]').setValue('震旦')
    expect(wrapper.findAll('.save-game-row')).toHaveLength(1)
    expect(wrapper.get('.save-game-row strong').text()).toBe('震旦.save')
    await wrapper.get('.save-game-row .primary-button').trigger('click')
    expect(wrapper.emitted('load')[0]).toEqual(['震旦.save'])
  })
})
