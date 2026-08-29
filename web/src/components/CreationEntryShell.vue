<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow: string
  description: string
  width?: 'standard' | 'wide'
}>(), {
  width: 'standard',
})
</script>

<template>
  <main class="creation-entry-page">
    <section class="creation-entry-workspace" :class="`is-${width}`">
      <header class="creation-entry-heading">
        <p>{{ eyebrow }}</p>
        <h1><slot name="title" /></h1>
        <small>{{ description }}</small>
      </header>
      <slot />
    </section>
  </main>
</template>

<style scoped>
.creation-entry-page {
  display: flex;
  min-height: 100%;
  overflow: auto;
  padding: 36px 22px 90px;
  color: var(--app-text, #303442);
  background-color: var(--app-canvas, #f8f9fc);
  background-image: var(--creation-bg-image, none);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
}

.creation-entry-workspace {
  width: min(820px, 100%);
  margin: auto;
}

.creation-entry-workspace.is-wide {
  width: min(940px, 100%);
}

.creation-entry-heading {
  display: grid;
  justify-items: center;
  margin-bottom: 30px;
  text-align: center;
}

.creation-entry-heading p {
  margin: 0 0 10px;
  color: #777cf7;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .16em;
}

.creation-entry-heading h1 {
  margin: 0;
  color: #262a37;
  font-size: clamp(28px, 3vw, 38px);
  line-height: 1.2;
  letter-spacing: -.035em;
}

.creation-entry-heading :deep(.creation-entry-accent) {
  color: #6263f5;
}

.creation-entry-heading small {
  max-width: 620px;
  margin-top: 10px;
  color: #9398a8;
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 880px) {
  .creation-entry-page { padding: 48px 22px 70px; }
}

@media (max-width: 620px) {
  .creation-entry-page { padding: 34px 14px 60px; }
  .creation-entry-heading small { max-width: 360px; }
}
</style>
