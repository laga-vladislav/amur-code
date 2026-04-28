<template>
  <div>
    <div class="inspector-section">
      <h4>Слайд</h4>

      <div class="inspector-row">
        <label>Имя</label>
        <input type="text" :value="slide.name || ''" @input="(e) => updateSlide({ name: e.target.value })" />
      </div>

      <div class="inspector-row">
        <label>Тип</label>
        <select :value="slide.slideType" @change="(e) => updateSlide({ slideType: e.target.value })">
          <option v-for="option in slideTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>

      <div v-if="docStore.mode === 'presentation'" class="inspector-row">
        <label>Номер</label>
        <label class="check-chip">
          <input type="checkbox" :checked="!slide.hideSlideNumber" @change="(e) => updateSlide({ hideSlideNumber: !e.target.checked })" />
          <span>Показывать на этом слайде</span>
        </label>
      </div>
    </div>

    <div class="inspector-section">
      <h4>
        <span>Фон</span>
        <select
          :value="slide.background?.type || 'color'"
          @change="(e) => changeBgType(e.target.value)"
          style="width: auto; padding: 3px 6px; font-size: 11px;"
        >
          <option v-for="option in backgroundTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </h4>

      <template v-if="slide.background?.type === 'color'">
        <div class="inspector-row">
          <label>Цвет</label>
          <ColorChip :value="slide.background.value" @change="(value) => updateSlide({ background: { type: 'color', value } })" />
        </div>
      </template>

      <template v-else-if="slide.background?.type === 'image'">
        <div class="inspector-row">
          <label>Файл</label>
          <select
            :value="slide.background.assetId || ''"
            @change="(e) => updateSlide({ background: { ...slide.background, type: 'image', assetId: e.target.value, fit: slide.background.fit || 'cover' } })"
          >
            <option value="">— не выбрано —</option>
            <option v-for="asset in imageAssets" :key="asset.id" :value="asset.id">{{ asset.fileName || asset.id }}</option>
          </select>
        </div>

        <div class="inspector-row">
          <label>Загрузить</label>
          <input type="file" accept="image/*" @change="onUploadBg" />
        </div>

        <div class="inspector-row">
          <label>Подгонка</label>
          <select :value="slide.background.fit || 'cover'" @change="(e) => updateSlide({ background: { ...slide.background, fit: e.target.value } })">
            <option v-for="option in fitOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
      </template>

      <template v-else>
        <div class="inspector-row">
          <label>Начало</label>
          <ColorChip :value="slide.background.from || '#FFFFFF'" @change="(value) => updateSlide({ background: { ...slide.background, from: value } })" />
        </div>

        <div class="inspector-row">
          <label>Конец</label>
          <ColorChip :value="slide.background.to || '#000000'" @change="(value) => updateSlide({ background: { ...slide.background, to: value } })" />
        </div>

        <div class="inspector-row">
          <label>Угол</label>
          <input type="number" :value="slide.background.angle || 0" @input="(e) => updateSlide({ background: { ...slide.background, angle: +e.target.value } })" />
          <span class="num-suffix">°</span>
        </div>
      </template>
    </div>

    <div class="inspector-section">
      <h4>Заметки</h4>
      <textarea :value="slide.notes || ''" rows="4" @input="(e) => updateSlide({ notes: e.target.value })" />
    </div>
  </div>
</template>

<script>
import ColorChip from './ColorChip.vue';
import { useDocumentStore } from '../../stores/document.js';
import { api } from '../../api/client.js';

const SLIDE_TYPE_OPTIONS = [
  { value: 'title', label: 'Титульный' },
  { value: 'text', label: 'Текстовый' },
  { value: 'image', label: 'С изображением' },
  { value: 'bullets', label: 'Список' },
  { value: 'conclusion', label: 'Финальный' },
];

const BACKGROUND_TYPE_OPTIONS = [
  { value: 'color', label: 'Цвет' },
  { value: 'image', label: 'Изображение' },
  { value: 'gradient', label: 'Градиент' },
];

const FIT_OPTIONS = [
  { value: 'cover', label: 'Заполнить область' },
  { value: 'contain', label: 'Вписать целиком' },
  { value: 'stretch', label: 'Растянуть' },
];

export default {
  name: 'SlideInspector',
  components: { ColorChip },
  props: { slide: { type: Object, required: true } },
  data() {
    return {
      slideTypeOptions: SLIDE_TYPE_OPTIONS,
      backgroundTypeOptions: BACKGROUND_TYPE_OPTIONS,
      fitOptions: FIT_OPTIONS,
    };
  },
  computed: {
    docStore() { return useDocumentStore(); },
    imageAssets() {
      return (this.docStore.doc?.assets || []).filter((asset) => asset.type === 'image');
    },
  },
  methods: {
    updateSlide(props) {
      this.docStore.run({
        type: 'slide.update',
        slideId: this.slide.id,
        payload: { props },
      });
    },
    changeBgType(type) {
      let background;
      if (type === 'color') background = { type: 'color', value: '#FFFFFF' };
      else if (type === 'image') background = { type: 'image', assetId: '', fit: 'cover' };
      else background = { type: 'gradient', from: '#FFFFFF', to: '#111827', angle: 90 };
      this.updateSlide({ background });
    },
    async onUploadBg(event) {
      const file = event.target.files?.[0];
      if (!file) return;
      const asset = await api.uploadAsset(file);
      this.docStore.addAsset(asset);
      this.updateSlide({
        background: { type: 'image', assetId: asset.id, fit: this.slide.background?.fit || 'cover' },
      });
      event.target.value = '';
    },
  },
};
</script>
