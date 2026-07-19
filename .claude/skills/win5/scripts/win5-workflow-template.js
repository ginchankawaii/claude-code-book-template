// WIN5予想ワークフローのテンプレート。
// 使い方: このファイルをセッションの作業ディレクトリにコピーし、
// (1) 下の legs 配列を当日のデータで置き換え（argsは使わない — 環境により渡らない）
// (2) 日付を当日に置換
// (3) Workflowツールに {scriptPath: "コピー先"} で渡して実行する。
export const meta = {
  name: 'win5-prediction',
  description: 'WIN5をエージェントチームで本格予想（調査→パネル→券面構成）',
  phases: [
    { title: '調査', detail: '5レースを並列で徹底調査' },
    { title: '予想', detail: '本命派・穴党・期待値の3視点パネル' },
    { title: '券面', detail: 'リスク管理と買い目構成（予算上限内）' },
  ],
}

// ▼▼▼ ここを当日のデータで置き換える ▼▼▼
const RACE_DATE = '20XX年X月X日(土)'
const BUDGET_POINTS = 50 // 予算上限(円)÷100
const legs = [
  {
    leg: 1,
    candidate: 'レース名候補（開催場・コース想定）',
    horses: [
      { num: 1, name: '馬名', odds: 0.0 },
      // ...全頭ぶん。オッズは画像と突き合わせて再確認すること
    ],
  },
  // ...leg5まで
]
// ▲▲▲ ここまで ▲▲▲

const RESEARCH_SCHEMA = {
  type: 'object',
  properties: {
    leg: { type: 'integer' },
    race_name: { type: 'string' },
    venue: { type: 'string' },
    race_no: { type: 'string' },
    course: { type: 'string', description: '例: ダート1700m右回り' },
    class: { type: 'string' },
    start_time: { type: 'string' },
    identification_confidence: { type: 'string', description: 'high/medium/low とその根拠' },
    pace_scenario: { type: 'string', description: '逃げ先行馬と展開予想' },
    horses: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          num: { type: 'integer' },
          name: { type: 'string' },
          odds: { type: 'number' },
          evaluation: { type: 'string', description: '近走・適性・騎手など。情報が無ければ「情報なし」' },
        },
        required: ['num', 'name'],
      },
    },
    ana_candidates: {
      type: 'array',
      description: '単勝10倍以上で狙える根拠のある穴馬',
      items: {
        type: 'object',
        properties: {
          num: { type: 'integer' },
          name: { type: 'string' },
          reason: { type: 'string' },
        },
        required: ['num', 'reason'],
      },
    },
    chaos_score: { type: 'number', description: 'このレースが荒れる可能性 0-10' },
    sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['leg', 'race_name', 'horses', 'chaos_score'],
}

const PANEL_SCHEMA = {
  type: 'object',
  properties: {
    role: { type: 'string' },
    legs: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          leg: { type: 'integer' },
          picks: { type: 'array', items: { type: 'integer' }, description: '推奨馬番を自信順に' },
          ana: { type: 'array', items: { type: 'integer' }, description: '特に推す穴馬番' },
          comment: { type: 'string' },
        },
        required: ['leg', 'picks', 'comment'],
      },
    },
    overall: { type: 'string', description: '全体戦略の要約' },
  },
  required: ['legs', 'overall'],
}

const TICKET_SCHEMA = {
  type: 'object',
  properties: {
    plans: {
      type: 'array',
      description: '購入プラン（複数口可）。各プランの点数=各レース選択頭数の積',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string', description: '例: 本線フォーメーション / 大穴サブ' },
          legs: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                leg: { type: 'integer' },
                nums: { type: 'array', items: { type: 'integer' } },
                rationale: { type: 'string' },
              },
              required: ['leg', 'nums'],
            },
          },
          points: { type: 'integer' },
        },
        required: ['name', 'legs', 'points'],
      },
    },
    total_points: { type: 'integer' },
    cost_yen: { type: 'integer' },
    recommended_yen: { type: 'integer', description: '推奨購入額（円）' },
    hit_scenarios: { type: 'string', description: '的中パターンと想定配当レンジ' },
    risk_notes: { type: 'string' },
  },
  required: ['plans', 'total_points', 'cost_yen', 'recommended_yen', 'hit_scenarios'],
}

phase('調査')
log('5レースの調査エージェントを並列起動')
const research = (await parallel(legs.map(l => () =>
  agent(
    `あなたはJRA競馬の調査アナリストです。${RACE_DATE}のWIN5対象${l.leg}レース目を徹底調査してください。\n` +
    `【判明している情報】出走馬と単勝オッズ: ${JSON.stringify(l.horses)}\n` +
    `【レース名の有力候補】${l.candidate}（馬名で検索して必ず裏取りすること。候補が違えば正しいレースを特定）\n` +
    `【手順】まずToolSearchで WebSearch と WebFetch をロード。馬名+日付やレース名候補で検索し、(1)レース特定（開催場/レース番号/芝ダ/距離/クラス/発走時刻）、(2)各馬の近走成績・騎手・斤量・コース適性、(3)逃げ先行馬と展開、(4)根拠のある穴馬(単勝10倍以上)、(5)荒れ度(0-10)を調べる。\n` +
    `【注意】netkeiba・JRA等は直接取得が403になりやすい。sports.yahoo.co.jp、スポーツ紙系、予想ブログ等を試し、検索結果のスニペットだけでも積極的に情報を拾う。個別馬の情報が取れない場合は「情報なし」とし、オッズ構造から推論した評価と区別すること。捏造は厳禁。\n` +
    `最終出力は構造化データで返す。legは${l.leg}。`,
    { label: `調査:leg${l.leg} ${l.candidate}`, phase: '調査', schema: RESEARCH_SCHEMA }
  )
))).filter(Boolean)

if (research.length < legs.length) log(`警告: 調査完了は${research.length}/${legs.length}レース。欠けたレースはオッズのみで分析続行`)

const researchJson = JSON.stringify(research)

phase('予想')
const roles = [
  {
    key: '本命派',
    prompt: 'あなたは的中率重視の本命派アナリスト。各レースで勝つ確率が最も高い馬を冷静に序列化する。人気馬でも危険な人気馬（過剰人気・距離不安・休み明け等）は指摘するが、1番人気を軽視する場合はその旨を明示する。各レース1〜3頭に絞る。',
  },
  {
    key: '穴党',
    prompt: 'あなたは大穴発掘専門の穴党アナリスト。単勝10倍以上、できれば20倍超で勝ち切るシナリオが描ける馬を各レースで探す。展開利（単騎逃げ・ハイペースの差し込み）、馬場適性、昇級/降級、乗り替わり強化、季節の格言（夏は牝馬・軽斤量・上がり馬）を根拠に。荒れ度が高いレースを特定し「ここで穴を狙え」と明言する。根拠なき穴推しは禁止。',
  },
  {
    key: '期待値',
    prompt: 'あなたはオッズ分析・期待値のクオンツ。単勝オッズから市場の想定勝率(1/オッズ÷控除率補正)を計算し、調査情報と突き合わせて過剰人気馬と過小評価馬を特定する。WIN5は点数積み上げ型なので「どのレースを1頭に絞りどのレースを広げるべきか」の分散配分を提案する。',
  },
]
log('3視点の予想パネルを起動')
const views = (await parallel(roles.map(r => () =>
  agent(
    `${r.prompt}\n${RACE_DATE}のWIN5対象5レースについて、調査班の以下のレポートを読み、各レース(leg1〜5)の推奨馬番を自信順に挙げ、理由を述べよ。\n` +
    `【調査レポート】${researchJson}\n` +
    `必要なら自分でも追加のWeb検索をしてよい（ToolSearchでWebSearchをロード）。roleは「${r.key}」。`,
    { label: `パネル:${r.key}`, phase: '予想', schema: PANEL_SCHEMA }
  )
))).filter(Boolean)

phase('券面')
const viewsJson = JSON.stringify(views)
let ticket = null
for (let attempt = 0; attempt < 3; attempt++) {
  ticket = await agent(
    `あなたはWIN5の券面構成を担当するリスクマネージャー。以下の調査レポートと3人のアナリスト（本命派・穴党・期待値）の見解を統合し、最終買い目を構成せよ。\n` +
    `【制約】WIN5は1点100円。総点数は絶対に${BUDGET_POINTS}点以内。プランは複数口に分けてよいが、プラン間で同一の組み合わせが重複しないよう、どこかのレースで選択馬を完全に分けること（重複ゼロ設計）。各プランの点数は各レース選択頭数の積で、自分で正確に計算すること。\n` +
    `【教訓ルール】(1)1番人気を消す場合でも最低1点はヘッジとしてどこかのプランに残す。完全消しは2番人気以下のみ。(2)取消明け・休み明けでも調教好評価の人気馬を「実戦裏付けなし」だけで消さない。(3)「情報なし」の馬が多い荒れ警報レースは1頭でも広げるか、捨てる場合はリスクとして明示する。\n` +
    `【方針】堅いレース（断然人気が信頼できるレース）は1頭に絞り、荒れ度の高いレースに点数を回す。推奨購入額（総点数×100円）も提示。的中シナリオ（どの組み合わせで当たればどの程度の配当帯か）を説明すること。\n` +
    `${attempt > 0 ? '【重要】前回の出力は点数計算が制約違反だった。各プランのpointsを選択頭数の積として計算し直し、合計を制約内に収めよ。\n' : ''}` +
    `【調査レポート】${researchJson}\n【パネル見解】${viewsJson}`,
    { label: `券面構成${attempt > 0 ? `(再試行${attempt})` : ''}`, phase: '券面', schema: TICKET_SCHEMA }
  )
  if (!ticket) continue
  let sum = 0
  for (const p of ticket.plans) {
    let prod = 1
    for (const lg of p.legs) prod *= lg.nums.length
    p.points = prod
    sum += prod
  }
  ticket.total_points = sum
  ticket.cost_yen = sum * 100
  if (sum > 0 && sum <= BUDGET_POINTS) break
  log(`点数${sum}が制約違反のため再構成`)
}

return { research, views, ticket }
