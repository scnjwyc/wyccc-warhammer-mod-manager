import { describe, expect, it } from 'vitest'
import { GAME_OPTIONS, gameLabelKey } from '../games'

describe('supported games', () => {
  it('lists every Total War game with a Steam Workshop', () => {
    expect(Object.fromEntries(GAME_OPTIONS.map(game => [game.id, game.appId]))).toEqual({
      warhammer3: '1142710',
      warhammer2: '594570',
      warhammer: '364360',
      three_kingdoms: '779340',
      pharaoh_dynasties: '2951630',
      pharaoh: '1937780',
      troy: '1099410',
      thrones_of_britannia: '712100',
      attila: '325610',
      rome2: '214950',
      shogun2: '34330',
      rome_remastered: '885970',
    })
    expect(GAME_OPTIONS.find(game => game.id === 'shogun2').workshopPathPlaceholder).toContain('34330')
    expect(GAME_OPTIONS.find(game => game.id === 'rome_remastered')).toMatchObject({
      modFormat: 'feral_directory',
      supportsSaveGames: false,
    })
  })

  it('resolves labels without falling back to Warhammer III for supported games', () => {
    expect(gameLabelKey('pharaoh_dynasties')).toBe('settings.gamePharaohDynasties')
    expect(gameLabelKey('unknown')).toBe('settings.gameWarhammer3')
  })
})
