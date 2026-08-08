export const GAME_OPTIONS = Object.freeze([
  { id: 'warhammer3', labelKey: 'settings.gameWarhammer3', appId: '1142710', installDir: 'Total War WARHAMMER III' },
  { id: 'warhammer2', labelKey: 'settings.gameWarhammer2', appId: '594570', installDir: 'Total War WARHAMMER II' },
  { id: 'warhammer', labelKey: 'settings.gameWarhammer', appId: '364360', installDir: 'Total War WARHAMMER' },
  { id: 'three_kingdoms', labelKey: 'settings.gameThreeKingdoms', appId: '779340', installDir: 'Total War THREE KINGDOMS' },
  { id: 'pharaoh_dynasties', labelKey: 'settings.gamePharaohDynasties', appId: '2951630', installDir: 'Total War PHARAOH DYNASTIES' },
  { id: 'pharaoh', labelKey: 'settings.gamePharaoh', appId: '1937780', installDir: 'Total War PHARAOH' },
  { id: 'troy', labelKey: 'settings.gameTroy', appId: '1099410', installDir: 'Total War Saga TROY' },
  { id: 'thrones_of_britannia', labelKey: 'settings.gameThronesOfBritannia', appId: '712100', installDir: 'Total War Saga Thrones of Britannia' },
  { id: 'attila', labelKey: 'settings.gameAttila', appId: '325610', installDir: 'Total War Attila' },
  { id: 'rome2', labelKey: 'settings.gameRome2', appId: '214950', installDir: 'Total War Rome II' },
  { id: 'shogun2', labelKey: 'settings.gameShogun2', appId: '34330', installDir: 'Total War SHOGUN 2' },
  {
    id: 'rome_remastered',
    labelKey: 'settings.gameRomeRemastered',
    appId: '885970',
    installDir: 'Total War ROME REMASTERED',
    modFormat: 'feral_directory',
    supportsSaveGames: false,
  },
].map(game => Object.freeze({
  modFormat: 'pack',
  supportsSaveGames: true,
  ...game,
  gamePathPlaceholder: `...\\steamapps\\common\\${game.installDir}`,
  workshopPathPlaceholder: `...\\workshop\\content\\${game.appId}`,
})))

export const gameLabelKey = gameId => (
  GAME_OPTIONS.find(game => game.id === gameId)?.labelKey || GAME_OPTIONS[0].labelKey
)
