{% comment %}
  Smith's Tees — Fundraising Landing Page
  Template: page.fundraising.liquid
  Install: Online Store > Themes > Edit Code > Templates > Add template (page, fundraising)
{% endcomment %}

<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap');

  /* Hide announcement bars on this page only */
  .announcement-bar-section,
  .utility-bar {
    display: none !important;
  }

  .st-page * { box-sizing: border-box; margin: 0; padding: 0; }

  .st-page {
    font-family: 'DM Sans', sans-serif;
    color: #0f1f3d;
    overflow-x: hidden;
    --tee-navy: #0f1f3d;
    --tee-gold: #f5a623;
    --tee-gold-light: #fdf0d5;
    --tee-cream: #fafaf7;
    --tee-muted: #6b7280;
    --tee-border: #e5e7eb;
  }

  /* HERO */
  .st-hero {
    background: var(--tee-navy);
    padding: 5rem 2rem 6rem;
    text-align: center;
    position: relative;
    overflow: hidden;
  }
  .st-hero::before {
    content: '';
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(45deg, rgba(245,166,35,0.04) 0px, rgba(245,166,35,0.04) 1px, transparent 1px, transparent 40px);
    pointer-events: none;
  }
  .st-eyebrow {
    display: inline-block;
    background: var(--tee-gold);
    color: var(--tee-navy);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .12em;
    text-transform: uppercase;
    padding: 6px 16px;
    border-radius: 99px;
    margin-bottom: 1.5rem;
  }
  .st-hero h1 {
    font-family: 'Bebas Neue', sans-serif;
    font-size: clamp(3rem, 9vw, 6rem);
    line-height: .95;
    color: #fff;
    margin-bottom: 1.25rem;
    letter-spacing: .02em;
  }
  .st-hero h1 span { color: var(--tee-gold); }
  .st-hero-sub {
    font-size: 1.1rem;
    color: rgba(255,255,255,0.72);
    max-width: 520px;
    margin: 0 auto 2.5rem;
    line-height: 1.6;
  }
  .st-cta-btn {
    display: inline-block;
    background: var(--tee-gold);
    color: var(--tee-navy);
    font-weight: 600;
    font-size: 1rem;
    padding: 16px 36px;
    border-radius: 8px;
    text-decoration: none;
    cursor: pointer;
    border: none;
    font-family: 'DM Sans', sans-serif;
    transition: transform .15s, box-shadow .15s;
  }
  .st-cta-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(245,166,35,.4);
  }
  .st-hero-note {
    margin-top: 1rem;
    font-size: .85rem;
    color: rgba(255,255,255,.45);
  }

  /* TRUST BAR */
  .st-trust {
    background: #fff;
    border-bottom: 1px solid var(--tee-border);
    padding: 1.25rem 2rem;
    text-align: center;
  }
  .st-trust p {
    font-size: .8rem;
    color: var(--tee-muted);
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: .75rem;
  }
  .st-trust-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
  }
  .st-trust-tag {
    background: var(--tee-cream);
    border: 1px solid var(--tee-border);
    border-radius: 99px;
    font-size: .8rem;
    color: var(--tee-muted);
    padding: 5px 14px;
  }

  /* SECTIONS */
  .st-section {
    padding: 4rem 2rem;
    max-width: 900px;
    margin: 0 auto;
  }
  .st-label {
    font-size: .75rem;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--tee-gold);
    font-weight: 600;
    margin-bottom: .5rem;
  }
  .st-section h2 {
    font-family: 'Bebas Neue', sans-serif;
    font-size: clamp(2rem, 5vw, 3rem);
    line-height: 1;
    margin-bottom: .75rem;
  }
  .st-section-sub {
    font-size: 1rem;
    color: var(--tee-muted);
    max-width: 500px;
    line-height: 1.6;
    margin-bottom: 2.5rem;
  }

  /* STEPS */
  .st-steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 1.5rem;
  }
  .st-step {
    background: #fff;
    border: 1px solid var(--tee-border);
    border-radius: 12px;
    padding: 1.5rem;
  }
  .st-step-num {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--tee-gold-light);
    color: var(--tee-navy);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.2rem;
    margin-bottom: 1rem;
  }
  .st-step h3 { font-size: .95rem; font-weight: 600; margin-bottom: .4rem; }
  .st-step p { font-size: .85rem; color: var(--tee-muted); line-height: 1.5; }

  /* CALCULATOR */
  .st-calc-wrap {
    background: var(--tee-navy);
    padding: 4rem 2rem;
  }
  .st-calc-inner { max-width: 700px; margin: 0 auto; }
  .st-calc-wrap .st-label { color: var(--tee-gold); }
  .st-calc-wrap h2 { color: #fff; font-family: 'Bebas Neue', sans-serif; font-size: clamp(2rem, 5vw, 3rem); line-height: 1; margin-bottom: .75rem; }
  .st-calc-wrap .st-section-sub { color: rgba(255,255,255,.55); }
  .st-calc-card {
    background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 16px;
    padding: 2rem;
  }
  .st-calc-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .st-calc-row label { font-size: .85rem; color: rgba(255,255,255,.65); min-width: 120px; }
  .st-calc-row input[type=range] { flex: 1; accent-color: var(--tee-gold); }
  .st-calc-row .st-val { font-size: .95rem; font-weight: 600; color: #fff; min-width: 80px; text-align: right; }
  .st-earnings {
    background: var(--tee-gold);
    border-radius: 12px;
    padding: 1.5rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .st-earn-label { font-size: .85rem; color: var(--tee-navy); font-weight: 600; }
  .st-earn-big { font-family: 'Bebas Neue', sans-serif; font-size: 2.8rem; color: var(--tee-navy); line-height: 1; }
  .st-earn-sub { font-size: .75rem; color: rgba(15,31,61,.6); margin-top: 2px; }

  /* PRICING */
  .st-pricing-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 1rem;
    margin-bottom: 2.5rem;
  }
  .st-price-card {
    background: #fff;
    border: 1px solid var(--tee-border);
    border-radius: 12px;
    padding: 1.5rem;
    text-align: center;
  }
  .st-price-type { font-size: .75rem; text-transform: uppercase; letter-spacing: .1em; color: var(--tee-muted); margin-bottom: .5rem; }
  .st-price-amt { font-family: 'Bebas Neue', sans-serif; font-size: 2.5rem; color: var(--tee-navy); line-height: 1; }
  .st-price-earn { font-size: .8rem; color: #16a34a; font-weight: 600; margin-top: .5rem; }
  .st-price-earn span { background: #dcfce7; border-radius: 99px; padding: 3px 10px; }

  /* PERSONALIZATION */
  .st-personalize {
    background: #fff;
    border: 1px solid var(--tee-border);
    border-radius: 16px;
    padding: 2rem;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    align-items: center;
  }
  @media (max-width: 560px) { .st-personalize { grid-template-columns: 1fr; } }
  .st-personalize h3 { font-family: 'Bebas Neue', sans-serif; font-size: 1.6rem; margin-bottom: .5rem; }
  .st-personalize p { font-size: .9rem; color: var(--tee-muted); line-height: 1.6; }
  .st-name-badge {
    background: var(--tee-navy);
    border-radius: 12px;
    padding: 1.25rem;
    text-align: center;
    font-family: 'Bebas Neue', sans-serif;
    color: #fff;
    letter-spacing: .06em;
    line-height: 1.4;
  }
  .st-badge-num { color: var(--tee-gold); font-size: 2.5rem; display: block; }
  .st-badge-name { font-size: 1.1rem; }
  .st-badge-role { font-size: .75rem; color: rgba(255,255,255,.5); margin-top: .5rem; font-family: 'DM Sans', sans-serif; font-weight: 400; letter-spacing: 0; }

  /* FAQ */
  .st-faq-list { display: grid; gap: 1rem; }
  .st-faq-item {
    background: #fff;
    border: 1px solid var(--tee-border);
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
  }
  .st-faq-item h4 { font-size: .95rem; font-weight: 600; margin-bottom: .4rem; }
  .st-faq-item p { font-size: .85rem; color: var(--tee-muted); line-height: 1.6; }

  /* CTA BOTTOM */
  .st-cta-bottom {
    background: var(--tee-gold);
    padding: 4rem 2rem;
    text-align: center;
  }
  .st-cta-bottom h2 {
    font-family: 'Bebas Neue', sans-serif;
    font-size: clamp(2.2rem, 6vw, 4rem);
    color: var(--tee-navy);
    margin-bottom: .75rem;
  }
  .st-cta-bottom p { font-size: 1rem; color: rgba(15,31,61,.65); margin-bottom: 2rem; }
  .st-cta-form {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    max-width: 520px;
    margin: 0 auto;
  }
  .st-cta-form input {
    flex: 1;
    min-width: 200px;
    padding: 14px 16px;
    border: 1.5px solid rgba(15,31,61,.25);
    border-radius: 8px;
    font-size: .95rem;
    background: #fff;
    outline: none;
    font-family: 'DM Sans', sans-serif;
  }
  .st-cta-form input:focus { border-color: var(--tee-navy); }
  .st-cta-form button {
    background: var(--tee-navy);
    color: #fff;
    border: none;
    padding: 14px 28px;
    border-radius: 8px;
    font-size: .95rem;
    font-weight: 600;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    white-space: nowrap;
    transition: opacity .15s;
  }
  .st-cta-form button:hover { opacity: .85; }
  .st-cta-legal { font-size: .75rem; color: rgba(15,31,61,.45); margin-top: .75rem; }

  .st-divider { height: 1px; background: var(--tee-border); max-width: 900px; margin: 0 auto; }
</style>

<div class="st-page">

  <!-- HERO -->
  <div class="st-hero">
    <div class="st-eyebrow">Zero upfront cost to your organization</div>
    <h1>Fundraise With<br><span>Custom Tees</span></h1>
    <p class="st-hero-sub">Smith's Tees partners with schools, sports teams, and community orgs to raise money — no inventory, no hassle, no risk. We handle everything.</p>
    <button class="st-cta-btn" onclick="document.getElementById('st-start').scrollIntoView({behavior:'smooth'})">Start Your Fundraiser</button>
    <p class="st-hero-note">Your org keeps 60–65% of profit on every tee sold</p>
  </div>

  <!-- TRUST BAR -->
  <div class="st-trust">
    <p>Great for</p>
    <div class="st-trust-tags">
      <span class="st-trust-tag">Schools &amp; PTAs</span>
      <span class="st-trust-tag">Youth Sports Teams</span>
      <span class="st-trust-tag">AAU Programs</span>
      <span class="st-trust-tag">Booster Clubs</span>
      <span class="st-trust-tag">Community Orgs</span>
      <span class="st-trust-tag">Church Groups</span>
    </div>
  </div>

  <!-- HOW IT WORKS -->
  <div class="st-section">
    <p class="st-label">The Process</p>
    <h2>Simple as 1, 2, 3</h2>
    <p class="st-section-sub">We take care of design, printing, and shipping. Your only job is to share the link.</p>
    <div class="st-steps">
      <div class="st-step">
        <div class="st-step-num">1</div>
        <h3>Tell us about your org</h3>
        <p>Share your logo, colors, and a little about your team or group. We'll reach out within 24 hours.</p>
      </div>
      <div class="st-step">
        <div class="st-step-num">2</div>
        <h3>We design your tee</h3>
        <p>We create a custom design using your brand. Nothing goes live until you approve it — 100% your call.</p>
      </div>
      <div class="st-step">
        <div class="st-step-num">3</div>
        <h3>Share &amp; sell</h3>
        <p>We launch your fundraiser store. Orders ship directly to buyers. You collect your earnings at the end.</p>
      </div>
      <div class="st-step">
        <div class="st-step-num">4</div>
        <h3>Get paid</h3>
        <p>Receive 60–65% of the profit on every tee sold. No caps, no minimums, no surprises.</p>
      </div>
    </div>
  </div>

  <div class="st-divider"></div>

  <!-- EARNINGS CALCULATOR -->
  <div class="st-calc-wrap">
    <div class="st-calc-inner">
      <p class="st-label">Earnings Calculator</p>
      <h2>How much could you raise?</h2>
      <p class="st-section-sub">A team of 25 players where each family buys 2–3 tees = $325–500 for your org. See for yourself.</p>
      <div class="st-calc-card">
        <div class="st-calc-row">
          <label>Tees sold</label>
          <input type="range" min="10" max="300" value="50" id="st-qty" step="5" oninput="stCalc()" onchange="stCalc()">
          <span class="st-val" id="st-qty-val">50</span>
        </div>
        <div class="st-calc-row">
          <label>Style</label>
          <input type="range" min="0" max="2" value="0" id="st-style" step="1" oninput="stCalc()" onchange="stCalc()">
          <span class="st-val" id="st-style-val">Kids ($25)</span>
        </div>
        <div class="st-earnings">
          <div>
            <div class="st-earn-label">Your estimated earnings</div>
            <div class="st-earn-sub">at 62% profit split</div>
          </div>
          <div style="text-align:right">
            <div class="st-earn-big" id="st-earn-amt">$275</div>
            <div class="st-earn-sub" id="st-earn-sub">from 50 tees</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- PRICING -->
  <div class="st-section">
    <p class="st-label">Pricing</p>
    <h2>Transparent pricing, always</h2>
    <p class="st-section-sub">Fixed prices. No hidden fees. Ships directly to your supporters across the US.</p>
    <div class="st-pricing-grid">
      <div class="st-price-card">
        <div class="st-price-type">Kids Tee</div>
        <div class="st-price-amt">$25</div>
        <div class="st-price-earn"><span>Org earns ~$5–6</span></div>
      </div>
      <div class="st-price-card">
        <div class="st-price-type">Adult Unisex</div>
        <div class="st-price-amt">$30</div>
        <div class="st-price-earn"><span>Org earns ~$6–7</span></div>
      </div>
      <div class="st-price-card">
        <div class="st-price-type">Plus Sizes</div>
        <div class="st-price-amt">$33–35</div>
        <div class="st-price-earn"><span>Org earns ~$7–8</span></div>
      </div>
    </div>

    <!-- SHIPPING -->
    <div style="background:#f3f4f6;border-radius:12px;padding:1.25rem 1.5rem;margin-bottom:1.5rem;display:flex;align-items:center;gap:1rem;">
      <div style="width:40px;height:40px;background:#0f1f3d;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <div style="width:16px;height:16px;border:2px solid #f5a623;border-radius:2px;"></div>
      </div>
      <div>
        <div style="font-size:.9rem;font-weight:600;color:#0f1f3d;margin-bottom:3px;">Ships direct to every buyer</div>
        <div style="font-size:.82rem;color:#6b7280;line-height:1.5;">Every order ships straight to the buyer's door anywhere in the US — no boxes to manage, no distribution headaches for your org.</div>
      </div>
    </div>
    <p style="font-size:.82rem;color:var(--tee-muted);margin-bottom:2.5rem;">At the end of your campaign we cut one check to your organization. Simple and transparent.</p>

  </div>

  <div class="st-divider"></div>

  <!-- DESIGN STYLES -->
  <div class="st-section">
    <p style="font-size:.95rem;font-weight:600;color:#0f1f3d;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.5rem;">Design Options</p>
    <h2>Three styles. All proven sellers.</h2>
    <p class="st-section-sub">Right now your org is probably buying swag. With Smith's Tees, we share the profit instead.</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.5rem;margin-bottom:1rem;">

      <!-- LOGO TEE -->
      <div style="background:#fff;border:1px solid var(--tee-border);border-radius:12px;overflow:hidden;">
        <div style="background:#f3f4f6;padding:2.5rem 1.5rem;display:flex;align-items:center;justify-content:center;min-height:180px;">
          <div style="text-align:center;">
            <div style="width:72px;height:72px;background:#0f1f3d;border-radius:8px;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;border:2px dashed #f5a623;">
              <div style="font-size:.65rem;font-weight:600;color:#f5a623;text-transform:uppercase;letter-spacing:.08em;text-align:center;line-height:1.4;">Org<br>Logo</div>
            </div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:1.1rem;color:#0f1f3d;letter-spacing:.05em;">YOUR ORG NAME</div>
            <div style="font-size:.7rem;color:#6b7280;margin-top:4px;">Est. 2024</div>
          </div>
        </div>
        <div style="padding:1.25rem;">
          <div style="font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:#6b7280;margin-bottom:.4rem;">Logo Tee</div>
          <div style="font-size:.9rem;font-weight:600;color:#0f1f3d;margin-bottom:.4rem;">Clean &amp; Professional</div>
          <div style="font-size:.82rem;color:#6b7280;line-height:1.5;">Your logo, your colors, on a quality tee. Timeless and works for any org.</div>
        </div>
      </div>

      <!-- STATEMENT TEE -->
      <div style="background:#0f1f3d;border:1px solid var(--tee-border);border-radius:12px;overflow:hidden;">
        <div style="background:#0a1628;padding:2.5rem 1.5rem;display:flex;align-items:center;justify-content:center;min-height:180px;">
          <div style="text-align:center;">
            <div style="font-family:'Bebas Neue',sans-serif;font-size:1.3rem;color:#f5a623;letter-spacing:.08em;line-height:1.1;">YOUR TEAM</div>
            <div style="width:40px;height:2px;background:#f5a623;margin:8px auto;"></div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:1.8rem;color:#fff;letter-spacing:.06em;line-height:1;">BUILT DIFFERENT</div>
          </div>
        </div>
        <div style="padding:1.25rem;">
          <div style="font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:#f5a623;margin-bottom:.4rem;">Statement Tee</div>
          <div style="font-size:.9rem;font-weight:600;color:#fff;margin-bottom:.4rem;">Bold &amp; Wearable</div>
          <div style="font-size:.82rem;color:rgba(255,255,255,.6);line-height:1.5;">Built around your identity. People wear these beyond game day — which means more sales.</div>
        </div>
      </div>

      <!-- PERSONALIZED TEE -->
      <div style="background:#fff;border:1px solid var(--tee-border);border-radius:12px;overflow:hidden;">
        <div style="background:#f3f4f6;padding:2.5rem 1.5rem;display:flex;align-items:center;justify-content:center;min-height:180px;">
          <div style="text-align:center;">
            <div style="font-family:'Bebas Neue',sans-serif;font-size:.9rem;color:#6b7280;letter-spacing:.08em;margin-bottom:4px;">YOUR ORG</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:2rem;color:#0f1f3d;letter-spacing:.06em;line-height:1;">#22</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:1.1rem;color:#0f1f3d;letter-spacing:.08em;">JOHNSON</div>
            <div style="display:inline-block;margin-top:8px;background:#f5a623;border-radius:99px;font-size:.65rem;font-weight:600;color:#0f1f3d;padding:3px 10px;letter-spacing:.06em;text-transform:uppercase;">Proud Mom</div>
          </div>
        </div>
        <div style="padding:1.25rem;">
          <div style="font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:#6b7280;margin-bottom:.4rem;">Personalized Tee</div>
          <div style="font-size:.9rem;font-weight:600;color:#0f1f3d;margin-bottom:.4rem;">Player names &amp; numbers</div>
          <div style="font-size:.82rem;color:#6b7280;line-height:1.5;">Parents and fans order tees with their player's name and number. Huge seller for sports teams.</div>
        </div>
      </div>

    </div>
    <p style="font-size:.82rem;color:var(--tee-muted);text-align:center;">Not sure which fits your org? We'll help you decide — no commitment required.</p>
  </div>


  <div class="st-section">
    <p style="font-size:.95rem;font-weight:600;color:#0f1f3d;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.5rem;">Questions</p>
    <h2>Good to know</h2>
    <p class="st-section-sub" style="margin-bottom:2rem">Answers to what most orgs ask before getting started.</p>
    <div class="st-faq-list">
      <div class="st-faq-item">
        <h4>Does our organization pay anything upfront?</h4>
        <p>No. There is zero cost to get started. You only earn — every tee sold puts money directly toward your cause.</p>
      </div>
      <div class="st-faq-item">
        <h4>How does the design process work?</h4>
        <p>You send us your logo and colors. We create a custom design and send it to you for approval. Nothing goes live until you say so.</p>
      </div>
      <div class="st-faq-item">
        <h4>Who handles printing and shipping?</h4>
        <p>We do. Orders are fulfilled via high-quality DTG (direct-to-garment) printing and shipped directly to each buyer's door — no boxes to manage, no inventory to store, no distribution headaches for your org.</p>
      </div>
      <div class="st-faq-item">
        <h4>Can you support organizations anywhere in the US?</h4>
        <p>Yes — we work with schools, teams, and orgs nationwide. Because everything is printed and shipped on demand, location is never a limitation.</p>
      </div>
      <div class="st-faq-item">
        <h4>What kind of designs do you create?</h4>
        <p>Three styles, all popular. Logo tees feature your org's brand — clean and professional. Statement tees are built around your identity, like "Your Team – Built Different" — these drive more excitement because people actually want to wear them beyond game day. And personalized tees with player names and numbers are a huge hit with sports families. Best of all, we can offer more than one style in your fundraiser shop — mix and match to give supporters more options and increase overall sales.</p>
      </div>
      <div class="st-faq-item">
        <h4>How long does a fundraiser run?</h4>
        <p>Typically 2–4 weeks, but we'll work with your timeline. Some groups do seasonal campaigns, others run them year-round.</p>
      </div>
    </div>
  </div>

  <!-- CTA BOTTOM -->
  <div class="st-cta-bottom" id="st-start">
    <h2>Ready to start your fundraiser?</h2>
    <p>Leave your info and we'll be in touch within one business day.</p>
    {% form 'contact' %}
      <div class="st-cta-form">
        <input type="hidden" name="contact[tags]" value="fundraiser-inquiry">
        <input type="text" name="contact[name]" placeholder="Organization name" required>
        <input type="email" name="contact[email]" placeholder="Your email" required>
        <input type="hidden" name="contact[body]" value="New fundraiser inquiry submitted from the fundraising landing page.">
        <button type="submit">Let's Talk</button>
      </div>
      {% if form.posted_successfully? %}
        <p style="margin-top:1rem;font-weight:600;color:#0f1f3d;">Got it! We'll be in touch within one business day.</p>
      {% endif %}
      {% if form.errors %}
        <p style="margin-top:1rem;font-weight:600;color:#991b1b;">Something went wrong — please try again.</p>
      {% endif %}
    {% endform %}
    <p class="st-cta-legal">No commitment required. No spam, ever.</p>
  </div>

</div>

<script>
  var stStyles = [
    { label: 'Kids ($25)', profit: 5.5 },
    { label: 'Adult ($30)', profit: 6.5 },
    { label: 'Plus ($34)', profit: 7.5 }
  ];
  function stCalc() {
    var q = parseInt(document.getElementById('st-qty').value);
    var s = parseInt(document.getElementById('st-style').value);
    document.getElementById('st-qty-val').textContent = q;
    document.getElementById('st-style-val').textContent = stStyles[s].label;
    var earn = Math.round(q * stStyles[s].profit);
    document.getElementById('st-earn-amt').textContent = '$' + earn.toLocaleString();
    document.getElementById('st-earn-sub').textContent = 'from ' + q + ' tees';
  }
  document.addEventListener('DOMContentLoaded', function() {
    var qtySlider = document.getElementById('st-qty');
    var styleSlider = document.getElementById('st-style');
    if (qtySlider) {
      qtySlider.addEventListener('touchmove', function(e) { e.stopPropagation(); stCalc(); }, { passive: true });
      qtySlider.addEventListener('touchend', stCalc, { passive: true });
    }
    if (styleSlider) {
      styleSlider.addEventListener('touchmove', function(e) { e.stopPropagation(); stCalc(); }, { passive: true });
      styleSlider.addEventListener('touchend', stCalc, { passive: true });
    }
    stCalc();
  });
</script>
