<?php

namespace Drupal\translator_app\Controller;

use Drupal\Core\Controller\ControllerBase;
use Drupal\node\NodeInterface;
use GuzzleHttp\Exception\GuzzleException;

class TranslatorAppController extends ControllerBase {

  public function translateNode(NodeInterface $node) {
    $config = $this->config('translator_app.settings');
    $base_url = rtrim($config->get('api_base_url'), '/');
    $api_key = $config->get('api_key');

    if (!$base_url || !$api_key) {
      $this->messenger()->addError($this->t('Translator App API URL and key are required.'));
      return $this->redirect('translator_app.settings');
    }

    $body = '';
    if ($node->hasField('body') && !$node->get('body')->isEmpty()) {
      $body = $node->get('body')->value;
    }

    $payload = [
      'external_content_id' => 'drupal-node-' . $node->id(),
      'content_type' => $node->bundle(),
      'title' => $node->label(),
      'source_language' => $config->get('source_language') ?: 'en',
      'target_language' => $config->get('target_language') ?: 'es',
      'format' => 'html',
      'text' => $body,
      'metadata' => [
        'drupal_node_id' => $node->id(),
        'drupal_bundle' => $node->bundle(),
      ],
    ];
    if ($config->get('translation_provider')) {
      $payload['provider'] = $config->get('translation_provider');
    }
    if ($config->get('translation_model')) {
      $payload['model'] = $config->get('translation_model');
    }

    try {
      $response = \Drupal::httpClient()->post($base_url . '/api/v1/translate/html', [
        'headers' => [
          'Content-Type' => 'application/json',
          'X-API-Key' => $api_key,
        ],
        'json' => $payload,
        'timeout' => 45,
      ]);
    }
    catch (GuzzleException $exception) {
      $this->messenger()->addError($exception->getMessage());
      return $this->redirect('entity.node.edit_form', ['node' => $node->id()]);
    }

    $payload = json_decode((string) $response->getBody(), TRUE);
    if ($response->getStatusCode() >= 400) {
      $this->messenger()->addError($payload['detail'] ?? $this->t('Translator App API request failed.'));
      return $this->redirect('entity.node.edit_form', ['node' => $node->id()]);
    }

    $this->messenger()->addStatus($this->t('Translation completed. Use the TMGMT provider for full review and Drupal Content Translation write-back workflows.'));
    return [
      '#type' => 'details',
      '#title' => $this->t('Translated HTML'),
      '#open' => TRUE,
      'translation' => [
        '#markup' => '<pre>' . htmlspecialchars($payload['translated_text'] ?? '', ENT_QUOTES, 'UTF-8') . '</pre>',
      ],
    ];
  }
}
