# Executive Command - Design System (Corporate Precision)

## Visual Identity & Brand Personality
**Executive Command** là một ngôn ngữ thiết kế được xây dựng cho các ứng dụng doanh nghiệp cấp cao, tập trung vào hiệu suất, sự chính xác và quyền lực. Phong cách này được truyền cảm hứng từ các trạm Bloomberg, thiết kế tối giản của Thụy Sĩ (Swiss Minimalism) và các giao diện tài chính hiện đại.

- **Tính cách thương hiệu:** Quyền lực, Chính xác, Tin cậy, Hiệu quả.
- **Nguyên tắc thiết kế:** Thông tin dày đặc nhưng rõ ràng, phân cấp thị giác nghiêm ngặt, sử dụng không gian trắng có mục đích và chú trọng vào dữ liệu.

---

## Color Palette

### Primary Colors
- **Biscay Navy:** `#16315E`
  - *Usage:* Headers, primary navigation, sidebar, primary buttons, and background for authentication screens. The anchor of the system.
- **Bright Turquoise:** `#10CFC9`
  - *Usage:* Primary actions (Approve), active states, progress bar fills, and positive indicators. Provides a high-energy contrast to the Navy.

### Neutral Colors
- **Off-White (Background):** `#F4F5F7` / `#F8F9FA`
  - *Usage:* Main application background to reduce eye strain.
- **Pure White (Surface):** `#FFFFFF`
  - *Usage:* Cards, panels, modals, and input fields.
- **Slate 900 (Text Primary):** `#0F172A`
  - *Usage:* Primary headings, body text, and high-readability labels.
- **Slate 500 (Text Muted):** `#64748B`
  - *Usage:* Secondary metadata, timestamps, and placeholder text.
- **Border Gray:** `#E2E8F0`
  - *Usage:* Dividers and element borders. Shadows are minimized in favor of 1px borders.

### Semantic Colors (Risk & Status)
- **High Risk:** `#DC2626` (Red 600) / `#EF4444`
- **Moderate Risk:** `#F59E0B` (Amber 500)
- **Low Risk/Success:** `#10B981` (Emerald 500)

---

## Typography

Hệ thống sử dụng hai font chữ bổ trợ cho nhau để cân bằng giữa tính kỹ thuật và khả năng đọc.

### Headings: Space Grotesk
Font chữ geometric sans-serif mang lại cảm giác kỹ thuật, hiện đại và quyết đoán.
- **Display:** 32px, Bold (Tracking -0.02em)
- **H1:** 24px, SemiBold
- **H2:** 18px, Medium (Often Uppercase with 0.05em tracking)

### Body & Data: IBM Plex Sans / Inter Tight
Font chữ tối ưu cho khả năng đọc dữ liệu và văn bản dài.
- **Body Large:** 16px, Regular (Line-height 1.5)
- **Body Small:** 14px, Regular
- **Data Mono (IBM Plex Mono / JetBrains Mono):** 12px-13px. Sử dụng cho các con số tài chính, mã ID và các bảng dữ liệu dày đặc. *Tabular Numerals* phải được bật.

---

## UI Components & Design Tokens

### Shape & Geometry
- **Border Radius:**
  - `0px` (Sharp): Dành cho headers, sidebar và các thành phần mang tính "Brutalist".
  - `4px - 8px`: Dành cho các thẻ (cards), nút bấm (buttons) và các thành phần tương tác để làm mềm giao diện một cách tinh tế.
- **Borders:** Sử dụng 1px border (`#E2E8F0`) thay vì đổ bóng (shadows) để duy trì vẻ ngoài phẳng và chuyên nghiệp.

### Buttons
- **Primary Action (Approve):** Nền Bright Turquoise, chữ Navy hoặc White.
- **Secondary Action (Reject):** Outlined hoặc Ghost style với màu Red hoặc Navy.
- **Navigation:** Nền Navy với biểu tượng/chữ màu trắng hoặc Turquoise khi active.

### Data Visualization
- **Progress Bars:** Chiều cao 8px, bo góc. Track màu xám nhạt, phần đã sử dụng màu Navy, phần đang xem xét màu Turquoise, phần vượt ngân sách màu Red.
- **Risk Indicators:** Sử dụng dải màu 4px (Vertical Strip) ở mép trái của các thẻ danh sách để chỉ thị mức độ rủi ro nhanh chóng.

---

## Layout Patterns

### Mobile (Handheld Precision)
- **Command Center:** Feed dạng thẻ cuộn dọc, chiều cao cố định để quét nhanh.
- **Action Sheets:** Sử dụng bottom sheets cho các hành động xác nhận, tích hợp các lý do từ chối có sẵn (rejection presets).

### Desktop (Mission Control)
- **3-Pane Layout:** Sidebar (64px) + List View (35%) + Detail/Analysis View (65%).
- **Split-Screen Analysis:** So sánh tài liệu gốc (PDF) với các phân tích AI theo tỷ lệ 50/50.

---

## CSS Variables (Tokens)

```css
:root {
  --color-primary: #16315E; /* Biscay Navy */
  --color-action: #10CFC9;  /* Bright Turquoise */
  --color-bg: #F4F5F7;      /* Application BG */
  --color-surface: #FFFFFF; /* Card Surface */
  --color-text-main: #0F172A;
  --color-text-muted: #64748B;
  --color-risk: #DC2626;

  --font-display: 'Space Grotesk', sans-serif;
  --font-body: 'IBM Plex Sans', sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;

  --radius-card: 8px;
  --radius-button: 4px;
}
```
