<template>
  <div class="home-shell">
    <header class="home-header">
      <div class="home-logo">
        <div class="mark">A</div>
        <div>
          <div class="name">Amur Code</div>
          <div class="tag">AI · Презентации</div>
        </div>
      </div>
      <nav class="home-nav">
        <a class="active">Главная</a>
        <a @click.prevent="scrollTo('decks')">Презентации</a>
        <a @click.prevent="scrollTo('templates')">Шаблоны</a>
      </nav>
      <div class="spacer" />
      <button class="tb-btn ghost" style="gap:8px;">
        <AcIcon name="search" :size="14" /> Поиск <span class="ac-kbd" style="margin-left:6px;">⌘K</span>
      </button>
      <button class="tb-btn icon ghost" title="Уведомления"><AcIcon name="bell" :size="16" /></button>
      <div class="home-avatar">{{ avatarInitials }}</div>
    </header>

    <!-- Hero composer -->
    <section class="hero">
      <div class="hero-top">
        <span class="ac-chip"><AcIcon name="sparkle" :size="12" /> AI генерация · Amur 4.0</span>
        <h1>
          Опиши идею
          <span class="accent">— получи презентацию</span>
        </h1>
        <p>Amur Code собирает структуру, верстает слайды и экспортирует в PPTX. Вы редактируете — он подстраивается.</p>
      </div>

      <div class="composer">
        <textarea
          class="composer-textarea"
          placeholder="Презентация для совета директоров: итоги Q3, 14 слайдов, акцент на retention и новый сегмент enterprise…"
          v-model="prompt"
          rows="3"
          @keydown.meta.enter.prevent="generate"
          @keydown.ctrl.enter.prevent="generate"
        />
        <div class="composer-bar">
          <SelectChip
            icon="layers"
            :value="composerTpl"
            :options="templateOptionLabels"
            @update="setComposerTpl"
            placeholder="Шаблон"
          />
          <SelectChip
            icon="grid"
            :value="length"
            :options="['6 слайдов','12 слайдов','20 слайдов']"
            @update="(v) => length = v"
          />
          <SelectChip
            icon="palette"
            :value="tone"
            :options="['Деловой','Дружелюбный','Академичный','Рекламный']"
            @update="(v) => tone = v"
          />
          <span class="composer-counter">{{ prompt.length }}/4000</span>
          <button
            class="tb-btn primary"
            style="padding:8px 14px;"
            :disabled="!composerTpl || !createName"
            @click="generate"
          >
            <AcIcon name="sparkle" :size="14" />
            Сгенерировать
            <span class="ac-kbd" style="background:rgba(255,255,255,0.30); color:rgba(255,255,255,0.92); border-color:rgba(255,255,255,0.35);">⏎</span>
          </button>
        </div>
      </div>

      <div class="examples">
        <button v-for="ex in examples" :key="ex" class="example-pill" @click="prompt = ex">
          <AcIcon name="sparkle" :size="11" /> {{ ex }}
        </button>
      </div>
    </section>

    <!-- Recent decks -->
    <section id="decks" class="section-row">
      <div class="section-head">
        <h2>Недавние презентации</h2>
        <span class="count">{{ presentations.length }}</span>
        <div class="spacer" />
        <button class="tb-btn primary" @click="openCreateDialog">
          <AcIcon name="plus" :size="13" /> Новая презентация
        </button>
      </div>
      <div v-if="presentations.length" class="deck-grid">
        <router-link
          v-for="(p, i) in presentations"
          :key="p.id"
          class="deck-card"
          :to="`/presentations/${p.id}`"
        >
          <div class="deck-card-preview" :style="previewStyle(i)">
            <div class="accent-bar" :style="{ background: accentFor(i) }" />
            <div class="preview-title">{{ p.name }}</div>
            <div class="preview-sub">{{ p.slideCount }} слайдов</div>
          </div>
          <div class="deck-card-meta">
            <div class="name">{{ p.name }}</div>
            <div class="info">
              <span>{{ p.slideCount }} слайдов</span>
              <span>·</span>
              <span style="font-family: var(--font-mono); color: var(--fg-3);">{{ p.id.slice(-8) }}</span>
            </div>
          </div>
        </router-link>
      </div>
      <div v-else class="empty-state">
        Пока нет презентаций. Опишите идею в композере выше или создайте новую вручную.
      </div>
    </section>

    <!-- Templates row -->
    <section id="templates" class="section-row" style="padding-bottom: 64px;">
      <div class="section-head">
        <h2>Шаблоны</h2>
        <span class="count">{{ templates.length }}</span>
        <div class="spacer" />
        <button class="tb-btn" @click="createTemplate">
          <AcIcon name="plus" :size="13" /> Новый шаблон
        </button>
      </div>
      <div v-if="templates.length" class="template-grid">
        <router-link
          v-for="(t, i) in templates"
          :key="t.id"
          class="template-card"
          :to="`/templates/${t.id}`"
        >
          <div class="preview" :style="{ background: `linear-gradient(140deg, ${accentFor(i)}30, rgba(20,20,32,0.40))` }">
            <div class="bars">
              <div class="bar accent" :style="{ background: accentFor(i) }"></div>
              <div class="bar"></div>
              <div class="bar"></div>
            </div>
          </div>
          <div>
            <div class="name">{{ t.name }}</div>
            <div class="meta">шаблон · {{ t.id.slice(-8) }}</div>
          </div>
        </router-link>
      </div>
      <div v-else class="empty-state">Шаблонов нет. Создайте новый, чтобы начать.</div>
    </section>

    <!-- Create dialog -->
    <div v-if="createOpen" class="modal-backdrop" @click.self="createOpen = false">
      <div class="modal">
        <div class="modal-head">
          <span>Новая презентация</span>
          <button class="tb-btn ghost icon" @click="createOpen = false">
            <AcIcon name="plus" :size="14" :stroke-width="2" style="transform: rotate(45deg);" />
          </button>
        </div>
        <div class="modal-body">
          <div class="inspector-row" style="margin:0;">
            <label>Название</label>
            <input type="text" v-model="createName" />
          </div>
          <div class="inspector-row" style="margin:0;">
            <label>Шаблон</label>
            <select v-model="createTemplateId">
              <option :value="null" disabled>— выберите шаблон —</option>
              <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
        </div>
        <div class="modal-foot">
          <button class="tb-btn ghost" @click="createOpen = false">Отмена</button>
          <button class="tb-btn primary" :disabled="!createTemplateId || !createName" @click="createPresentation">
            <AcIcon name="plus" :size="13" /> Создать
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import AcIcon from '../components/AcIcon.vue';
import SelectChip from '../components/SelectChip.vue';
import { api } from '../api/client.js';
import { makePresentation, slideFromLayout } from '../core/factories.js';
import { uid } from '../core/ids.js';

const ACCENTS = ['#ffb547', '#5a8ff0', '#38d2a4', '#ef5d4a', '#a85a05', '#92b8ff'];

export default {
  name: 'HomeView',
  components: { AcIcon, SelectChip },
  data() {
    return {
      presentations: [],
      templates: [],
      createOpen: false,
      createName: '',
      createTemplateId: null,
      prompt: '',
      length: '12 слайдов',
      tone: 'Деловой',
      composerTpl: null,
      examples: [
        'Презентация для инвесторов: SaaS B2B, 10 слайдов, упор на трекшн',
        'Внутренний отчёт по итогам Q3 для команды product-маркетинга',
        'Курс по основам аналитики для джуниоров — 15 уроков-слайдов',
      ],
    };
  },
  computed: {
    avatarInitials() {
      return 'А';
    },
    templateOptionLabels() {
      return this.templates.map((t) => t.name);
    },
  },
  async mounted() {
    await this.refresh();
    if (!this.composerTpl && this.templates.length) {
      this.composerTpl = this.templates[0].name;
    }
  },
  methods: {
    async refresh() {
      [this.presentations, this.templates] = await Promise.all([
        api.listPresentations(),
        api.listTemplates(),
      ]);
    },
    accentFor(i) { return ACCENTS[i % ACCENTS.length]; },
    previewStyle(i) {
      const c = this.accentFor(i);
      return { background: `linear-gradient(135deg, ${c}28, ${c}08)` };
    },
    setComposerTpl(name) { this.composerTpl = name; },
    scrollTo(id) {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    openCreateDialog() {
      if (!this.templates.length) {
        this.createTemplate();
        return;
      }
      this.createName = this.prompt
        ? this.prompt.split(/[.\n]/)[0].slice(0, 60)
        : 'Новая презентация';
      this.createTemplateId =
        this.templates.find((t) => t.name === this.composerTpl)?.id || this.templates[0].id;
      this.createOpen = true;
    },
    generate() {
      this.openCreateDialog();
    },
    async createPresentation() {
      const tpl = await api.getTemplate(this.createTemplateId);
      const doc = makePresentation({
        name: this.createName,
        templateId: tpl.id,
        theme: tpl.theme,
      });
      doc.slideSize = JSON.parse(JSON.stringify(tpl.slideSize));
      const titleLayout = tpl.layouts.find((l) => l.slideType === 'title') || tpl.layouts[0];
      if (titleLayout) doc.slides.push(slideFromLayout(titleLayout));
      if (this.prompt && doc.slides[0]) {
        doc.slides[0].notes = this.prompt;
      }
      const saved = await api.createPresentation(doc);
      this.createOpen = false;
      this.$router.push(`/presentations/${saved.id}`);
    },
    async createTemplate() {
      const id = uid('tmpl');
      const tpl = {
        schemaVersion: '1.0.0',
        documentType: 'template',
        id,
        name: 'Новый шаблон',
        slideSize: { widthEmu: 12192000, heightEmu: 6858000, ratio: '16:9' },
        theme: {
          fonts: { heading: 'Inter', body: 'Inter' },
          colors: {
            background: '#0C1016',
            text: '#F4F5F7',
            primary: '#FFB547',
            secondary: '#5A8FF0',
            accent: '#38D2A4',
          },
        },
        layouts: [
          {
            id: uid('layout'),
            name: 'Title',
            slideType: 'title',
            background: { type: 'color', value: '#0C1016' },
            elements: [],
          },
        ],
        assets: [],
      };
      const saved = await api.createTemplate(tpl);
      this.$router.push(`/templates/${saved.id}`);
    },
  },
};
</script>
