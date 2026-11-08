const palettes = [
  ['#E5D8C8', '#4D5141', '#59746A', '#E8BA98'],
  ['#DBE5DF', '#493B32', '#A46547', '#D9A982'],
  ['#EBDDCB', '#6E4332', '#876A89', '#F0C6A3'],
  ['#DDE3EB', '#303D45', '#607C91', '#BC8D6C'],
  ['#E9DCD8', '#A05D3C', '#A45652', '#ECC5A5'],
  ['#E4E4CC', '#77715D', '#697353', '#DCAC87'],
]

export function Avatar({ index, size = 56 }: { index: number; size?: number }) {
  const seat = ((index % 6) + 6) % 6
  const [background, hair, shirt, skin] = palettes[seat]
  return <svg width={size} height={size} viewBox="0 0 80 80" fill="none" aria-hidden="true" focusable="false">
    <circle cx="40" cy="40" r="40" fill={background} />
    {(seat === 0 || seat === 2 || seat === 4) && <path d="M20 43V30c0-15 11-21 21-21 15 0 22 10 22 23v25H19Z" fill={hair} />}
    <path d="M12 80c1-19 10-29 28-29s27 10 28 29" fill={shirt} />
    <path d="M33 48h14v13c-5 5-9 5-14 0Z" fill={skin} />
    <ellipse cx="40" cy="34" rx="17" ry="22" fill={skin} />
    {seat === 0 && <path d="M23 34V23c0-15 31-19 35 3-13-1-16-6-20-9-3 9-8 12-15 17Z" fill={hair} />}
    {seat === 1 && <path d="M23 31c-3-10 1-21 14-22 15-2 23 6 22 22l-6-10-10-2-17 7Z" fill={hair} />}
    {seat === 2 && <path d="M23 30c-2-21 29-28 35-7l-1 12-6-16c-10 8-15 8-28 11Z" fill={hair} />}
    {seat === 3 && <path d="M22 28c-1-22 36-26 37-2l-8-7-21 2-6 14Z" fill={hair} />}
    {seat === 4 && <><circle cx="59" cy="18" r="10" fill={hair} /><path d="M23 31c-1-23 32-29 35-5-12-3-12-8-12-8-7 9-14 12-23 13Z" fill={hair} /></>}
    {seat === 5 && <><path d="M23 28c-2-23 36-25 35 1l-9-10-16 2-9 15Z" fill={hair} /><path d="M27 42c7 10 19 11 26-1-1 13-7 17-13 17S28 53 27 42Z" fill={hair} /></>}
    <path d="M31 34h2m14 0h2" stroke="#383930" strokeWidth="2.6" strokeLinecap="round" />
    <path d="m39 36-1 6h3" stroke="#A37457" strokeWidth="1.4" strokeLinecap="round" />
    <path d="M35 47q5 3 10-1" stroke="#784C3E" strokeWidth="1.6" strokeLinecap="round" />
    {seat === 1 && <g stroke="#473D36" strokeWidth="1.5"><rect x="26" y="30" width="11" height="9" rx="3" /><rect x="43" y="30" width="11" height="9" rx="3" /><path d="M37 33h6" /></g>}
    {seat === 0 && <path d="m31 60 9 13 9-13M40 73v7" stroke="#E9E6DB" strokeWidth="2" />}
    {seat === 2 && <path d="M29 62q11 12 22 0" stroke="#D7C5DB" strokeWidth="3" />}
  </svg>
}
